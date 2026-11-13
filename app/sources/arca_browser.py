"""Headless-Chromium fetcher for arca.live.

arca.live uses Cloudflare Bot Management: the "Just a moment…" JS challenge
runs on every request from datacenter IPs. A real Chromium + residential proxy
clears the challenge automatically — httpx/curl_cffi cannot run CF's JS.

One warm context is reused across fetches (one cold launch per process).
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.config import HTTP_PROXY_URL, PPOMPPU_PROXY_URL, USER_AGENT

# Use the most specific available proxy (env PPOMPPU_PROXY_URL already falls
# back to HTTP_PROXY_URL in config, so this covers both env-var patterns).
_PROXY_URL = PPOMPPU_PROXY_URL or HTTP_PROXY_URL

log = logging.getLogger(__name__)

_CF_MARKERS = ("just a moment", "cf-browser-verification", "challenge-platform")
_CAPTCHA_MARKERS = ("cf-turnstile", "challenges.cloudflare.com/turnstile")
_CAPTCHA_COOLDOWN_SEC = 1800

_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font", "stylesheet"})
_BLOCKED_URL_PARTS = (
    "google-analytics", "googletagmanager", "doubleclick", "adservice",
    "/pagead/", "facebook.net", "criteo", "taboola", "outbrain",
    "adsystem", "amazon-adsystem", "clarity.ms", "hotjar",
    "googlesyndication", "adsbygoogle", "analytics", "gtag/js",
)
_ALLOWED_SCRIPT_HOSTS = ("arca.live",)

_lock = asyncio.Lock()
_pw = None
_browser = None
_context = None
_disabled_reason: str | None = None
_captcha_until = 0.0
_last_fetch_ts = 0.0
_MIN_GAP_SEC = 10.0


def _proxy_config() -> dict | None:
    raw = _PROXY_URL
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


def _looks_cf(html: str | None) -> bool:
    head = (html or "").lower()[:6000]
    return any(m in head for m in _CF_MARKERS)


def _looks_captcha(html: str | None) -> bool:
    head = (html or "")[:8000]
    return any(m in head for m in _CAPTCHA_MARKERS)


async def _route_filter(route) -> None:
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
        log.warning("arca browser disabled: %s", _disabled_reason)
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
        log.info("arca browser context up (proxy=%s)", bool(_PROXY_URL))
        return _context
    except Exception:  # noqa: BLE001
        log.exception("arca browser launch failed")
        await _hard_reset()
        return None


async def fetch_html(
    url: str,
    *,
    want_selector: str | None = None,
    settle_ms: int = 2000,
    max_rounds: int = 4,
    timeout: float = 35.0,
) -> str | None:
    """Return page HTML after Cloudflare clears, or None if unavailable."""
    global _captcha_until, _last_fetch_ts
    if not _PROXY_URL:
        return None  # no KR proxy → CF will just block
    if time.time() < _captcha_until:
        return None
    async with _lock:
        gap = time.time() - _last_fetch_ts
        if gap < _MIN_GAP_SEC:
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
                log.warning("arca browser hit Turnstile CAPTCHA; cooling off %ds", _CAPTCHA_COOLDOWN_SEC)
                _captcha_until = time.time() + _CAPTCHA_COOLDOWN_SEC
                await _hard_reset()
                return None
            rounds = 0
            while _looks_cf(html) and rounds < max_rounds and time.time() < deadline:
                rounds += 1
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
                await page.wait_for_timeout(settle_ms)
                html = await page.content()
                if not _looks_cf(html):
                    break
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=15000)
                except Exception:  # noqa: BLE001
                    pass
                html = await page.content()
            if _looks_captcha(html):
                log.warning("arca browser escalated to Turnstile mid-solve")
                _captcha_until = time.time() + _CAPTCHA_COOLDOWN_SEC
                await _hard_reset()
                return None
            if _looks_cf(html):
                log.warning("arca browser still CF-challenged after %d rounds: %s", rounds, url)
                # Keep the context alive — CF cookies may still be useful next
                # tick. Only reset on captcha (above) or crash (finally block).
                return None
            if want_selector:
                try:
                    await page.wait_for_selector(want_selector, timeout=6000)
                    html = await page.content()
                except Exception:  # noqa: BLE001
                    pass
            return html
        except Exception as exc:  # noqa: BLE001
            log.warning("arca browser fetch failed %s: %s", url, exc)
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
