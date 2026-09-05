"""Fetch popular Coupang products via the Partners Open API.

NOT YET VERIFIED AGAINST A LIVE RESPONSE. The endpoint path and the
response field names below follow Coupang Partners' published Open API
docs, but no real call has been made (no approved keys yet). When keys
are issued, run `POST /api/coupang/collect` and adjust `_to_raw()`'s
field mapping to whatever the live JSON actually returns.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.coupang.api import DOMAIN, signed_headers

# "Best category products" — the Golden Box style popular-items feed.
BEST_PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/bestcategories/{category_id}"
DEFAULT_LIMIT = 50


@dataclass
class RawCoupangDeal:
    product_id: str
    title: str
    price: int
    original_price: int | None
    discount_rate: float
    image_url: str | None
    product_url: str
    category_id: str


def _to_raw(item: dict, category_id: str) -> RawCoupangDeal | None:
    product_id = str(item.get("productId") or "")
    url = item.get("productUrl") or ""
    if not product_id or not url:
        return None
    price = int(item.get("productPrice") or 0)
    base = item.get("basePrice") or item.get("originalPrice")
    original = int(base) if base else None
    rate = 0.0
    if original and original > price > 0:
        rate = round((original - price) / original, 4)
    return RawCoupangDeal(
        product_id=product_id,
        title=str(item.get("productName") or "").strip(),
        price=price,
        original_price=original,
        discount_rate=rate,
        image_url=item.get("productImage") or None,
        product_url=url,
        category_id=category_id,
    )


async def fetch_golden_box(category_id: str, limit: int = DEFAULT_LIMIT) -> list[RawCoupangDeal]:
    path = BEST_PATH.format(category_id=category_id)
    path_and_query = f"{path}?limit={limit}&imageSize=512x512"
    headers = signed_headers("GET", path_and_query)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(DOMAIN + path_and_query, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    out: list[RawCoupangDeal] = []
    for item in (data.get("data") or []):
        raw = _to_raw(item, category_id)
        if raw:
            out.append(raw)
    return out
