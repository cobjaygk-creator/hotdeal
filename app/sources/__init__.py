from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.http_client import PoliteClient


@dataclass
class RawPost:
    source: str
    source_post_id: str
    url: str
    title: str
    body: str | None = None
    author: str | None = None
    posted_at: datetime | None = None
    votes: int = 0
    views: int = 0
    comments: int = 0
    extra: dict = field(default_factory=dict)


class Source(Protocol):
    name: str

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        ...
