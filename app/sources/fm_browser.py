"""Headless-Chromium fetcher for FMKorea.

FMKorea fronts /hotdeal (and post detail pages) with Akamai Bot Manager plus a
custom WebAssembly proof-of-work gate ("에펨코리아 보안 시스템"): the gate page
runs /mc/mc.php + /mc/mcw.php, which set a `lite_year` cookie and a WASM-derived
cookie, then reload with `?ddosCheckOnly=1`. httpx / curl_cffi cannot run the
WASM, so those requests get a permanent 430.

This module keeps one warm Chromium context (through the collector proxy) and
lets the gate JS solve itself. The context holds the cleared cookies for its
lifetime, so only the first request after a (re)launch pays the gate cost.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time

from app.config import (
    FMKOREA_BROWSER_ENABLED,
    FMKOREA_PROXY_SESSION_TTL_SEC,
    FMKOREA_PROXY_URL,
    USER_AGENT,
)

log = logging.getLogger(__name__)

# Gate-unique tokens from the "에펨코리아 보안 시스템" challenge page.
_GATE_MARKERS = ("ddosCheckOnly", "window.redirectCheck", "/mc/mc.php")

_lock = asyncio.Lock()
_pw = None
_browser = None
_context = None
_session_token = ""
_session_born = 0.0
_disabled_reason: str | None = None


def _proxy_config() -> dict | None:
    """Playwright proxy dict from FMKOREA_PROXY_URL, rotating {session} tokens."""
    global _session_token, _session_born
    raw = FMKOREA_PROXY_URL
    if not raw:
        return None
    now = time.time()
    if not _session_token or now - _session_born > max(60, FMKOREA_PROXY_SESSION_TTL_SEC):
        _session_token = secrets.token_hex(6)
        _session_born = now
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
        log.info("fmkorea browser context up (proxy=%s)", bool(FMKOREA_PROXY_URL))
        return _context
    except Exception:  # noqa: BLE001
        # Transient (proxy hiccup, OOM); reset and let the next tick retry.
        log.exception("fmkorea browser launch failed")
        await _hard_reset()
        return None


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
    if not FMKOREA_BROWSER_ENABLED:
        return None
    async with _lock:
        ctx = await _ensure_context()
        if ctx is None:
            return None
        page = None
        deadline = time.time() + timeout
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            html = await page.content()
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
            if _looks_gated(html):
                log.warning("fmkorea browser still gated after %d rounds: %s", rounds, url)
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
