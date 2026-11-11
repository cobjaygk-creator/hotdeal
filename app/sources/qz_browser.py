"""Headless-Chromium fetcher for Quasarzone.

Quasarzone uses Cloudflare's "Just a Moment" managed JS challenge: the browser
must run Cloudflare's JS (which sets cf_clearance + __cf_bm cookies) before the
real page is served. Plain HTTP clients and curl_cffi both fail because CF now
fingerprints TLS/JS execution beyond just the client-hello.

This module keeps one warm Chromium context (through the collector proxy) and
lets the CF challenge solve itself. After the first solve the cookies stay warm
so subsequent fetches in the same context are instant.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.config import (
    QUASARZONE_BROWSER_ENABLED,
    QUASARZONE_BROWSER_MIN_GAP_SEC,
    QUASARZONE_PROXY_URL,
    USER_AGENT,
)

log = logging.getLogger(__name__)

# Cloudflare "Just a Moment" challenge markers.
_CF_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "challenge-platform",
    "checking your browser",
    "enable javascript and cookies to continue",
)
# Cloudflare Turnstile (interactive CAPTCHA) — cannot solve headless.
_CAPTCHA_MARKERS = ("cf-turnstile", "challenges.cloudflare.com/turnstile")

_CAPTCHA_COOLDOWN_SEC = 1800

_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font", "stylesheet"})
_BLOCKED_URL_PARTS = (
    "google-analytics", "googletagmanager", "doubleclick", "adservice",
    "/pagead/", "facebook.net", "criteo", "taboola", "outbrain",
    "adsystem", "amazon-adsystem", "clarity.ms", "hotjar",
    "googlesyndication", "adsbygoogle",
)

_lock = asyncio.Lock()
_last_fetch_ts = 0.0
_pw = None
_browser = None
_context = None
_disabled_reason: str | None = None
_captcha_until = 0.0


def _proxy_config() -> dict | None:
    raw = QUASARZONE_PROXY_URL
    if not raw:
        return None
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


def _looks_challenged(html: str | None) -> bool:
    head = (html or "").lower()[:4000]
    return any(m in head for m in _CF_MARKERS)


def _looks_captcha(html: str | None) -> bool:
    head = (html or "").lower()[:6000]
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
        log.warning("quasarzone browser disabled: %s", _disabled_reason)
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
        proxy = _proxy_config()
        _context = await _browser.new_context(
            proxy=proxy,
            user_agent=USER_AGENT,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 2200},
        )
        _context.set_default_timeout(30_000)
        await _context.route("**/*", _route_filter)
        log.info(
            "quasarzone browser context up (proxy=%s)",
            bool(QUASARZONE_PROXY_URL),
        )
        return _context
    except Exception:  # noqa: BLE001
        log.exception("quasarzone browser launch failed")
        await _hard_reset()
        return None


async def _route_filter(route) -> None:
    try:
        req = route.request
        rtype = req.resource_type
        url = req.url
        drop = rtype in _BLOCKED_RESOURCE_TYPES or any(p in url for p in _BLOCKED_URL_PARTS)
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
    settle_ms: int = 2000,
    max_rounds: int = 5,
    timeout: float = 40.0,
) -> str | None:
    """Return page HTML after Cloudflare challenge clears, or None if unavailable."""
    global _captcha_until, _last_fetch_ts
    if not QUASARZONE_BROWSER_ENABLED:
        return None
    if time.time() < _captcha_until:
        log.debug("quasarzone browser in captcha cooldown, skipping")
        return None
    async with _lock:
        gap = time.time() - _last_fetch_ts
        if gap < QUASARZONE_BROWSER_MIN_GAP_SEC:
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
                    "quasarzone browser hit Turnstile CAPTCHA; cooling off %ds",
                    _CAPTCHA_COOLDOWN_SEC,
                )
                _captcha_until = time.time() + _CAPTCHA_COOLDOWN_SEC
                await _hard_reset()
                return None

            # Wait for CF "Just a Moment" challenge to auto-solve.
            rounds = 0
            while _looks_challenged(html) and rounds < max_rounds and time.time() < deadline:
                rounds += 1
                log.debug("quasarzone CF challenge round %d, waiting…", rounds)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
                await page.wait_for_timeout(settle_ms)
                html = await page.content()
                if not _looks_challenged(html):
                    break

            if _looks_captcha(html):
                log.warning("quasarzone browser escalated to Turnstile mid-solve")
                _captcha_until = time.time() + _CAPTCHA_COOLDOWN_SEC
                await _hard_reset()
                return None

            if _looks_challenged(html):
                log.warning(
                    "quasarzone browser still challenged after %d rounds: %s", rounds, url
                )
                await _hard_reset()
                return None

            if want_selector:
                try:
                    await page.wait_for_selector(want_selector, timeout=6000)
                    html = await page.content()
                except Exception:  # noqa: BLE001
                    pass

            log.info("quasarzone browser fetch ok rounds=%d url=%s", rounds, url)
            return html

        except Exception as exc:  # noqa: BLE001
            log.warning("quasarzone browser fetch failed %s: %s", url, exc)
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
