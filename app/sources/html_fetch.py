from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.parse import urlparse

from app.config import PPOMPPU_PROXY_URL
from app.http_client import FetchResult, PoliteClient, soft_block_reason
from app.sources import RawPost

ParseFn = Callable[[str], list[RawPost]]

# Railway datacenter IPs hit Cloudflare (or just hang) on these hosts; use the
# KR proxy first.
PROXY_FIRST_HOSTS = (
    "arca.live",
    "damoang.net",
    "quasarzone.com",
    "fmkorea.com",
    "coolenjoy.net",
)


def block_reason(result: FetchResult) -> str | None:
    head = (result.text or "").strip()
    if not head:
        return "empty body"
    reason = soft_block_reason(result.text)
    return f"blocked:{reason}" if reason else None


async def fetch_parsed(
    client: PoliteClient,
    url: str,
    parse_fn: ParseFn,
    *,
    encoding: str | None = None,
    timeout: float | None = None,
) -> list[RawPost]:
    host = (urlparse(url).hostname or "").lower()
    prefer_proxy = bool(PPOMPPU_PROXY_URL) and any(
        host == item or host.endswith("." + item) for item in PROXY_FIRST_HOSTS
    )
    proxy_tries: list[str | None] = []
    if prefer_proxy:
        proxy_tries.append(PPOMPPU_PROXY_URL)
        proxy_tries.append(None)
    else:
        proxy_tries.append(None)
        if PPOMPPU_PROXY_URL:
            proxy_tries.append(PPOMPPU_PROXY_URL)

    result = None
    reason = None
    last_exc: Exception | None = None
    for proxy in proxy_tries:
        try:
            result = await client.get(
                url,
                encoding=encoding,
                timeout=timeout or (20.0 if proxy else None),
                proxy=proxy,
            )
        except Exception as exc:  # noqa: BLE001 — timeout/conn error: try next exit
            last_exc = exc
            reason = f"fetch error:{type(exc).__name__}"
            continue
        if result.not_modified:
            return []
        reason = block_reason(result)
        if reason:
            # Same-client cookie warm-up for soft gates (esp. FMKorea).
            await asyncio.sleep(1.5)
            result = await client.get(
                url,
                encoding=encoding,
                timeout=timeout or (20.0 if proxy else None),
                proxy=proxy,
            )
            if result.not_modified:
                return []
            reason = block_reason(result)
        if not reason:
            break
    if result is None:
        raise RuntimeError(f"{reason or 'empty fetch'} ({url})") from last_exc
    if reason:
        raise RuntimeError(f"{reason} ({url})")
    posts = parse_fn(result.text)
    if not posts:
        head = " ".join((result.text or "")[:240].split())
        raise RuntimeError(
            f"parsed 0 posts bytes={len(result.content)} head={head!r} ({url})"
        )
    return posts
