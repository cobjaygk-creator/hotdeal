from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.http_client import PoliteClient


@dataclass
class RawSale:
    source_name: str
    source_post_id: str
    title: str
    source_url: str
    category_raw: str | None = None
    date_range: str | None = None
    discount_hint: str | None = None
    labels: list[str] = field(default_factory=list)
    deal_url: str | None = None
    location: str | None = None
    entry_code: str | None = None
    body: str | None = None


class FamilySource(Protocol):
    name: str

    async def fetch_latest(self, client: PoliteClient) -> list[RawSale]:
        ...
