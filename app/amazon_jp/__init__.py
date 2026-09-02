from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.http_client import PoliteClient


@dataclass
class RawAmazonDeal:
    asin: str
    title: str
    yen_price: int
    original_yen: int | None
    discount_rate: float
    image_url: str | None
    source: str
    source_url: str
    source_updated_at: str | None = None


class AmazonJpSource(Protocol):
    name: str

    async def fetch_latest(self, client: PoliteClient) -> list[RawAmazonDeal]: ...
