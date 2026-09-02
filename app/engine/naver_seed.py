from __future__ import annotations

import logging
import re
from html import unescape

import httpx

from app.config import (
    NAVER_CLIENT_ID,
    NAVER_CLIENT_SECRET,
    NAVER_SEED_CACHE_DAYS,
    NAVER_SEED_ENABLED,
    NAVER_SEED_MIN_SIMILARITY,
    USER_AGENT,
)
from app.db import get_meta, set_meta, utcnow_iso
from app.engine.dedupe import jaccard
from app.parse.normalize import tokenize
from app.parse.title import ParsedOffer

log = logging.getLogger(__name__)

API_URL = "https://openapi.naver.com/v1/search/shop.json"


async def seed_baseline_if_needed(conn, offer: ParsedOffer) -> int:
    """Seed price_points from Naver Shopping for a new product_key. Returns inserted count."""
    if not NAVER_SEED_ENABLED or not offer.product_key or not offer.product_name:
        return 0
    cache_key = f"naver_seed:{offer.product_key}"
    if await get_meta(conn, cache_key):
        return 0

    items = await _search(offer.product_name)
    await set_meta(conn, cache_key, utcnow_iso())
    if not items:
        return 0

    offer_tokens = offer.tokens or tokenize(offer.product_name)
    inserted = 0
    now = utcnow_iso()
    for item in items[:5]:
        title = _strip_html(item.get("title") or "")
        try:
            price = int(item.get("lprice") or 0)
        except (TypeError, ValueError):
            continue
        if price < 1000:
            continue
        sim = jaccard(offer_tokens, tokenize(title))
        if sim < NAVER_SEED_MIN_SIMILARITY:
            continue
        # Unique on (source, post_id); use negative synthetic post_id space via hash.
        synthetic_id = -abs(hash(f"{offer.product_key}:{price}:{title}")) % (10**9)
        try:
            await conn.execute(
                """
                INSERT INTO price_points(product_key, price, unit_price, seller, source, observed_at, post_id)
                VALUES(?, ?, NULL, ?, 'naver', ?, ?)
                ON CONFLICT(source, post_id) DO NOTHING
                """,
                (offer.product_key, price, item.get("mallName") or "네이버", now, synthetic_id),
            )
            inserted += 1
        except Exception as exc:  # noqa: BLE001
            log.debug("naver seed insert skip: %s", exc)
    if inserted:
        # Keep cache marker; also store soft expiry hint in value.
        await set_meta(
            conn,
            cache_key,
            f"{now}|days={NAVER_SEED_CACHE_DAYS}|n={inserted}",
        )
    return inserted


async def _search(query: str) -> list[dict]:
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "User-Agent": USER_AGENT,
    }
    params = {"query": query[:100], "display": 5, "sort": "asc"}
    try:
        async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
            resp = await client.get(API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            return list(data.get("items") or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("naver search failed q=%s err=%s", query[:40], exc)
        return []


def _strip_html(text: str) -> str:
    text = unescape(text or "")
    return re.sub(r"<[^>]+>", "", text).strip()
