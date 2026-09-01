from __future__ import annotations

from collections.abc import Callable

from app.http_client import FetchResult, PoliteClient
from app.sources import RawPost

ParseFn = Callable[[str], list[RawPost]]

_BLOCK_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "challenge-platform",
    "attention required",
    "access denied",
    "checking your browser",
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
) -> list[RawPost]:
    result = await client.get(url, encoding=encoding)
    if result.not_modified:
        return []
    reason = block_reason(result)
    if reason:
        raise RuntimeError(f"{reason} ({url})")
    posts = parse_fn(result.text)
    if not posts:
        head = " ".join((result.text or "")[:240].split())
        raise RuntimeError(
            f"parsed 0 posts bytes={len(result.content)} head={head!r} ({url})"
        )
    return posts
