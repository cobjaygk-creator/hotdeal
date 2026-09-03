from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape

import httpx

from app.config import (
    MARKET_COMPARE_CACHE_HOURS,
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
COMPARE_SIMILARITY = max(NAVER_SEED_MIN_SIMILARITY, 0.4)
COMPARE_DISPLAY = 12


async def seed_baseline_if_needed(conn, offer: ParsedOffer) -> int:
    """Seed price_points from Naver Shopping for a new product_key. Returns inserted count."""
    if not NAVER_SEED_ENABLED or not offer.product_key or not offer.product_name:
        return 0
    cache_key = f"naver_seed:{offer.product_key}"
    if await get_meta(conn, cache_key):
        return 0

    items = await _search(offer.product_name, display=5)
    await set_meta(conn, cache_key, utcnow_iso())
    if not items:
        return 0

    offer_tokens = offer.tokens or tokenize(offer.product_name)
    inserted = 0
    now = utcnow_iso()
    for item in items[:5]:
        parsed = _parse_item(item, offer_tokens)
        if not parsed:
            continue
        synthetic_id = -abs(hash(f"{offer.product_key}:{parsed['price']}:{parsed['title']}")) % (
            10**9
        )
        try:
            await conn.execute(
                """
                INSERT INTO price_points(product_key, price, unit_price, seller, source, observed_at, post_id)
                VALUES(?, ?, NULL, ?, 'naver', ?, ?)
                ON CONFLICT(source, post_id) DO NOTHING
                """,
                (
                    offer.product_key,
                    parsed["price"],
                    parsed["mall"],
                    now,
                    synthetic_id,
                ),
            )
            inserted += 1
        except Exception as exc:  # noqa: BLE001
            log.debug("naver seed insert skip: %s", exc)
    if inserted:
        await set_meta(
            conn,
            cache_key,
            f"{now}|days={NAVER_SEED_CACHE_DAYS}|n={inserted}",
        )
    return inserted


async def get_market_compare(
    conn,
    *,
    product_key: str,
    product_name: str,
    deal_price: int | None = None,
    deal_seller: str | None = None,
    deal_url: str | None = None,
    force: bool = False,
) -> dict:
    """Return per-mall Naver Shopping prices for a deal (cached)."""
    if not NAVER_SEED_ENABLED:
        return {
            "enabled": False,
            "items": [],
            "fetched_at": None,
            "note": "네이버 쇼핑 API 키(NAVER_CLIENT_ID / NAVER_CLIENT_SECRET)를 설정하면 시세를 보여 줍니다.",
        }
    if not product_key or not product_name:
        return {"enabled": True, "items": [], "fetched_at": None, "note": "상품명이 없어 비교할 수 없습니다."}

    cached = [] if force else await _load_listings(conn, product_key)
    fresh = bool(cached) and _is_fresh(cached[0].get("fetched_at"))
    if not fresh:
        await _refresh_listings(conn, product_key, product_name)
        cached = await _load_listings(conn, product_key)

    items = [
        {
            "mall": row["mall"],
            "title": row["title"],
            "price": int(row["price"]),
            "url": row.get("url") or "",
            "similarity": row.get("similarity"),
            "is_deal": False,
        }
        for row in cached
    ]
    if deal_price and deal_price >= 1000:
        deal_row = {
            "mall": (deal_seller or "현재 딜").strip() or "현재 딜",
            "title": product_name,
            "price": int(deal_price),
            "url": deal_url or "",
            "similarity": 1.0,
            "is_deal": True,
        }
        # Prefer deal row over same-mall Naver hit when prices are close.
        items = [x for x in items if not _same_mall(x["mall"], deal_row["mall"])]
        items.append(deal_row)

    items.sort(key=lambda x: (x["price"], 0 if x["is_deal"] else 1))
    fetched_at = cached[0]["fetched_at"] if cached else None
    note = None
    if not items:
        note = "비슷한 상품 시세를 찾지 못했습니다."
    return {
        "enabled": True,
        "items": items[:10],
        "fetched_at": fetched_at,
        "note": note,
    }


async def _refresh_listings(conn, product_key: str, product_name: str) -> int:
    items = await _search(product_name, display=COMPARE_DISPLAY)
    tokens = tokenize(product_name)
    now = utcnow_iso()
    # Replace previous snapshot for this key.
    await conn.execute("DELETE FROM market_listings WHERE product_key=?", (product_key,))
    best: dict[str, dict] = {}
    for raw in items:
        parsed = _parse_item(raw, tokens, min_sim=COMPARE_SIMILARITY)
        if not parsed:
            continue
        mall_key = parsed["mall"].casefold()
        prev = best.get(mall_key)
        if prev is None or parsed["price"] < prev["price"]:
            best[mall_key] = parsed
    for parsed in best.values():
        await conn.execute(
            """
            INSERT INTO market_listings(
                product_key, mall, title, price, url, product_id, similarity, fetched_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(product_key, mall, product_id) DO UPDATE SET
                title=excluded.title,
                price=excluded.price,
                url=excluded.url,
                similarity=excluded.similarity,
                fetched_at=excluded.fetched_at
            """,
            (
                product_key,
                parsed["mall"],
                parsed["title"],
                parsed["price"],
                parsed["url"],
                parsed["product_id"],
                parsed["similarity"],
                now,
            ),
        )
    await conn.commit()
    return len(best)


async def _load_listings(conn, product_key: str) -> list[dict]:
    cur = await conn.execute(
        """
        SELECT mall, title, price, url, product_id, similarity, fetched_at
        FROM market_listings
        WHERE product_key=?
        ORDER BY price ASC, mall ASC
        """,
        (product_key,),
    )
    return [dict(r) for r in await cur.fetchall()]


def _is_fresh(fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    try:
        raw = str(fetched_at).replace(" ", "T")
        if not re.search(r"Z$|[+-]\d{2}:?\d{2}$", raw):
            raw += "Z"
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return age <= timedelta(hours=max(1, MARKET_COMPARE_CACHE_HOURS))


def _parse_item(item: dict, offer_tokens: set[str], *, min_sim: float | None = None) -> dict | None:
    title = _strip_html(item.get("title") or "")
    try:
        price = int(item.get("lprice") or 0)
    except (TypeError, ValueError):
        return None
    if price < 1000 or not title:
        return None
    sim = jaccard(offer_tokens, tokenize(title))
    threshold = NAVER_SEED_MIN_SIMILARITY if min_sim is None else min_sim
    if sim < threshold:
        return None
    mall = (item.get("mallName") or "네이버").strip() or "네이버"
    product_id = str(item.get("productId") or "").strip() or str(
        abs(hash(f"{mall}:{title}:{price}")) % (10**12)
    )
    link = str(item.get("link") or "").strip()
    return {
        "mall": mall,
        "title": title[:180],
        "price": price,
        "url": link,
        "product_id": product_id[:64],
        "similarity": round(float(sim), 3),
    }


def _same_mall(a: str, b: str) -> bool:
    left = re.sub(r"\s+", "", (a or "").casefold())
    right = re.sub(r"\s+", "", (b or "").casefold())
    if not left or not right:
        return False
    return left == right or left in right or right in left


async def _search(query: str, display: int = 5) -> list[dict]:
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "User-Agent": USER_AGENT,
    }
    params = {"query": query[:100], "display": max(1, min(display, 20)), "sort": "asc"}
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
