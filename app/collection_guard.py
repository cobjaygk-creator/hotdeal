"""Bound remote list fetches before acquiring the shared SQLite writer lock."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.sources import RawPost

log = logging.getLogger(__name__)
SOURCE_FETCH_TIMEOUT_SECONDS = 60.0
SOURCE_FAILURE_COOLDOWN_SECONDS = 120.0


@dataclass
class FetchedSource:
    name: str
    posts: list[RawPost] = field(default_factory=list)
    error: Exception | None = None

    async def fetch_latest(self, client):
        if self.error is not None:
            raise self.error
        return self.posts


async def fetch_sources(sources, client, failures: dict) -> list[FetchedSource]:
    """Preserve failures for pipeline reporting; never cache a failed empty list.

    Requests remain sequential within a tier to limit external load, but no DB
    lock is held, so unrelated scheduler tiers can continue to collect/save.
    Cancellation must propagate, including during application shutdown.
    """
    results = []
    for source in sources:
        retry_at = failures.get(source.name, 0.0)
        if time.monotonic() < retry_at:
            results.append(FetchedSource(source.name, error=RuntimeError(
                "source cooling down after fetch failure"
            )))
            continue
        try:
            async with asyncio.timeout(SOURCE_FETCH_TIMEOUT_SECONDS):
                posts = await source.fetch_latest(client)
        except Exception as exc:
            failures[source.name] = time.monotonic() + SOURCE_FAILURE_COOLDOWN_SECONDS
            if isinstance(exc, TimeoutError):
                exc = TimeoutError(
                    f"list fetch exceeded {SOURCE_FETCH_TIMEOUT_SECONDS:g}s total budget"
                )
            log.warning("list fetch failed source=%s: %s", source.name, exc)
            results.append(FetchedSource(source.name, error=exc))
        else:
            failures.pop(source.name, None)
            results.append(FetchedSource(source.name, posts=posts))
    return results
