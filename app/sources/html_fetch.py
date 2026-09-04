from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from app.config import PPOMPPU_PROXY_URL
from app.http_client import FetchResult, PoliteClient
from app.sources import RawPost

ParseFn = Callable[[str], list[RawPost]]

# Railway datacenter IPs hit Cloudflare on these hosts; use the KR proxy first.
PROXY_FIRST_HOSTS = (
    "arca.live",
    "damoang.net",
    "quasarzone.com",
    "fmkorea.com",
)

_BLOCK_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "challenge-platform",
    "attention required",
    "access denied",
    "checking your browser",
    "enable javascript and cookies to continue",
    "please checking if the site connection is secure",
    "보안검사를 완료",
    "보안 검사",
)


def block_reason(result: FetchResult) -> str | None:
    head = (result.text or "")[:5000].lower()
    if not head.strip():
        return "empty body"
    for marker in _BLOCK_MARKERS:
        if marker in head:
            return f"blocked:{marker}"
    return None


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
    for proxy in proxy_tries:
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
        raise RuntimeError(f"empty fetch ({url})")
    if reason:
        raise RuntimeError(f"{reason} ({url})")
    posts = parse_fn(result.text)
    if not posts:
        head = " ".join((result.text or "")[:240].split())
        raise RuntimeError(
            f"parsed 0 posts bytes={len(result.content)} head={head!r} ({url})"
        )
    return posts
