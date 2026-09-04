"""Headless-Chromium fetcher for FMKorea.

FMKorea fronts /hotdeal (and post detail pages) with Akamai Bot Manager plus a
custom WebAssembly proof-of-work gate ("에펨코리아 보안 시스템"): the gate page
runs /mc/mc.php + /mc/mcw.php, which set a `lite_year` cookie and a WASM-derived
cookie, then reload with `?ddosCheckOnly=1`. httpx / curl_cffi cannot run the
WASM, so those requests get a permanent 430.

This module keeps one warm Chromium context (through the collector proxy) and
lets the gate JS solve itself. The context holds the cleared cookies for its
lifetime, so only the first request after a (re)launch pays the gate cost.

Durability: image/font/CSS/analytics requests are blocked so each page load is
a handful of requests; if FMKorea escalates the exit IP to a Cloudflare
Turnstile CAPTCHA (unsolvable headless) the module cools off for a while and
rotates the proxy {session} token so the next attempt lands on a fresh IP.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time

from app.config import (
    FMKOREA_BROWSER_ENABLED,
    FMKOREA_BROWSER_MIN_GAP_SEC,
    FMKOREA_PROXY_SESSION_TTL_SEC,
    FMKOREA_PROXY_URL,
    USER_AGENT,
)

log = logging.getLogger(__name__)

# Tokens unique to FMKorea's auto-solving WASM proof-of-work interstitial.
_GATE_MARKERS = ("ddosCheckOnly", "window.redirectCheck", "/mc/mc.php")
# The harder gate FMKorea escalates a flagged IP to: a Cloudflare Turnstile
# CAPTCHA. A headless browser cannot clear it — bail immediately.
_CAPTCHA_MARKERS = ("cf-turnstile", "challenges.cloudflare.com/turnstile", "/try_unblock.php")

_CAPTCHA_COOLDOWN_SEC = 1800  # after a Turnstile hit, leave the IP alone for a while
# Resource types the gate/board don't need — skipping them keeps each page load
# to a handful of requests so the exit IP looks less like a scraper.
_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font", "stylesheet"})
_BLOCKED_URL_PARTS = (
    "google-analytics", "googletagmanager", "doubleclick", "adservice",
    "/pagead/", "facebook.net", "connect.facebook", "criteo", "taboola",
    "outbrain", "adsystem", "amazon-adsystem", "clarity.ms", "hotjar",
    "google.com/ads", "googlesyndication", "adsbygoogle", "coupang",
    "linkprice", "acecounter", "analytics", "gtag/js", "wcslog",
)
# Scripts only from these hosts get through; everything else (ads, widgets,
# third-party JS) is aborted. The gate + board list only need fmkorea's own JS.
_ALLOWED_SCRIPT_HOSTS = ("fmkorea.com", "fmkorea.org")

_lock = asyncio.Lock()
_last_fetch_ts = 0.0
_pw = None
_browser = None
_context = None
_session_token = ""
_session_born = 0.0
_disabled_reason: str | None = None
_captcha_until = 0.0
_warned_no_session = False


def _rotate_session() -> None:
    global _session_token, _session_born
    _session_token = secrets.token_hex(6)
    _session_born = time.time()


def _proxy_config() -> dict | None:
    """Playwright proxy dict from FMKOREA_PROXY_URL, rotating {session} tokens."""
    global _warned_no_session
    raw = FMKOREA_PROXY_URL
    if not raw:
        return None
    now = time.time()
    if not _session_token or now - _session_born > max(60, FMKOREA_PROXY_SESSION_TTL_SEC):
        _rotate_session()
    if "{session}" not in raw and not _warned_no_session:
        _warned_no_session = True
        log.warning(
            "FMKOREA_PROXY_URL has no {session} placeholder — the browser will "
            "pin one exit IP and is more likely to get escalated to a CAPTCHA. "
            "Use a sticky-session endpoint like "
            "http://USER-session-{session}:PASS@host:port"
        )
    raw = raw.replace("{session}", _session_token)
    # Split creds from host for Playwright's {server, username, password} shape.
    scheme, _, rest = raw.partition("://")
    if not rest:
        return {"server": raw}
    creds, _, hostport = rest.rpartition("@")
    server = f"{scheme}://{hostport}" if hostport else f"{scheme}://{rest}"
    cfg: dict = {"server": server}
    if creds:
        user, _, pw = creds.partition(":")
        cfg["username"] = user
        cfg["password"] = pw
    return cfg


def _looks_gated(html: str | None) -> bool:
    head = (html or "")[:6000]
    return any(m in head for m in _GATE_MARKERS)


def _looks_captcha(html: str | None) -> bool:
    head = (html or "")[:8000]
    return any(m in head for m in _CAPTCHA_MARKERS)


async def _ensure_context():
    global _pw, _browser, _context, _disabled_reason
    if _disabled_reason:
        return None
    if _context is not None:
        return _context
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001
        _disabled_reason = f"playwright import failed: {exc}"
        log.warning("fmkorea browser disabled: %s", _disabled_reason)
        return None
    try:
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        _context = await _browser.new_context(
            proxy=_proxy_config(),
            user_agent=USER_AGENT,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 2200},
        )
        _context.set_default_timeout(30_000)
        await _context.route("**/*", _route_filter)
        log.info(
            "fmkorea browser context up (proxy=%s session=%s)",
            bool(FMKOREA_PROXY_URL),
            _session_token[:6] or "-",
        )
        return _context
    except Exception:  # noqa: BLE001
        # Transient (proxy hiccup, OOM); reset and let the next tick retry.
        log.exception("fmkorea browser launch failed")
        await _hard_reset()
        return None


async def _route_filter(route) -> None:
    """Abort heavy / tracking resources; keep the document, fmkorea's own JS
    and the gate's wasm. Third-party scripts are dropped — the board list is
    server-rendered and the gate only needs fmkorea.com scripts."""
    try:
        req = route.request
        rtype = req.resource_type
        url = req.url
        drop = rtype in _BLOCKED_RESOURCE_TYPES or any(p in url for p in _BLOCKED_URL_PARTS)
        if not drop and rtype == "script":
            drop = not any(h in url for h in _ALLOWED_SCRIPT_HOSTS)
        await (route.abort() if drop else route.continue_())
    except Exception:  # noqa: BLE001
        try:
            await route.continue_()
        except Exception:  # noqa: BLE001
            pass


async def _hard_reset() -> None:
    global _pw, _browser, _context
    for closer in (
        getattr(_context, "close", None),
        getattr(_browser, "close", None),
        getattr(_pw, "stop", None),
    ):
        if closer is None:
            continue
        try:
            await closer()
        except Exception:  # noqa: BLE001
            pass
    _pw = _browser = _context = None


async def fetch_html(
    url: str,
    *,
    want_selector: str | None = None,
    settle_ms: int = 1500,
    max_rounds: int = 4,
    timeout: float = 35.0,
) -> str | None:
    """Return page HTML after the gate clears, or None if unavailable."""
    global _captcha_until, _last_fetch_ts
    if not FMKOREA_BROWSER_ENABLED:
        return None
    if time.time() < _captcha_until:
        return None  # still cooling off from a Turnstile hit
    async with _lock:
        # Rate-limit: full browser page loads burn residential-proxy GB.
        gap = time.time() - _last_fetch_ts
        if gap < FMKOREA_BROWSER_MIN_GAP_SEC:
            return None
        _last_fetch_ts = time.time()
        ctx = await _ensure_context()
        if ctx is None:
            return None
        page = None
        deadline = time.time() + timeout
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            html = await page.content()
            if _looks_captcha(html):
                log.warning(
                    "fmkorea browser hit a Turnstile CAPTCHA; cooling off %ds and "
                    "rotating the proxy session",
                    _CAPTCHA_COOLDOWN_SEC,
                )
                _captcha_until = time.time() + _CAPTCHA_COOLDOWN_SEC
                _rotate_session()
                await _hard_reset()  # next attempt rebuilds on the fresh session
                return None
            rounds = 0
            while _looks_gated(html) and rounds < max_rounds and time.time() < deadline:
                rounds += 1
                # Gate JS sets cookies then window.location.replace(...). Give it
                # room, then fall back to a manual reload with the check flag.
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
                await page.wait_for_timeout(settle_ms)
                html = await page.content()
                if not _looks_gated(html):
                    break
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=15000)
                except Exception:  # noqa: BLE001
                    pass
                html = await page.content()
            if _looks_captcha(html):
                log.warning("fmkorea browser escalated to Turnstile mid-solve")
                _captcha_until = time.time() + _CAPTCHA_COOLDOWN_SEC
                _rotate_session()
                await _hard_reset()
                return None
            if _looks_gated(html):
                log.warning("fmkorea browser still gated after %d rounds: %s", rounds, url)
                # Auto-gate that won't clear → this IP is going sour; move on.
                _rotate_session()
                await _hard_reset()
                return None
            if want_selector:
                try:
                    await page.wait_for_selector(want_selector, timeout=6000)
                    html = await page.content()
                except Exception:  # noqa: BLE001
                    pass
            return html
        except Exception as exc:  # noqa: BLE001
            log.warning("fmkorea browser fetch failed %s: %s", url, exc)
            # A dead context / browser must be rebuilt next call.
            if "closed" in str(exc).lower() or "crash" in str(exc).lower():
                await _hard_reset()
            return None
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass


async def shutdown() -> None:
    async with _lock:
        await _hard_reset()
