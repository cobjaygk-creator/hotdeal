from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.config import (
    BASELINE_DAYS,
    NAVER_SEED_ENABLED,
    RECENT_DEAL_HOURS,
)
from app.db import get_meta, set_meta, utcnow_iso
from app.engine.category import classify
from app.engine.dedupe import jaccard, prefers_non_ppomppu, should_merge
from app.engine.naver_seed import seed_baseline_if_needed
from app.engine.pricing import compute_baseline
from app.engine.scoring import score_offer
from app.parse.links import extract_mall_url
from app.parse.title import parse_title
from app.sources import RawPost
from app.sources.detail import enrich_from_list_body
from app.util.timeparse import to_iso

log = logging.getLogger(__name__)
_collect_meta_lock = asyncio.Lock()


def _source_category(post_row: dict) -> str | None:
    """`raw_json` is the RawPost.extra dict when post_row came straight off a
    fresh fetch, or the JSON text once it's round-tripped through the posts
    table (e.g. rebuild_recent_deals) — handle both."""
    raw = post_row.get("raw_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict):
        val = raw.get("source_category")
        if isinstance(val, str) and val.strip():
            return val
    return None


def post_to_row(post: RawPost, *, thumbnail_url: str | None = None) -> dict:
    return {
        "source": post.source,
        "source_post_id": post.source_post_id,
        "url": post.url,
        "title": post.title,
        "body": post.body,
        "author": post.author,
        "posted_at": to_iso(post.posted_at),
        "votes": post.votes,
        "views": post.views,
        "comments": post.comments,
        "collected_at": utcnow_iso(),
        "raw_json": post.extra or None,
        "thumbnail_url": thumbnail_url or (post.extra or {}).get("thumbnail_url"),
    }


async def ingest_posts(conn, posts: list[RawPost]) -> list[int]:
    ids: list[int] = []
    from app.db import upsert_post

    for post in posts:
        pid, _inserted = await upsert_post(conn, post_to_row(post))
        ids.append(pid)
        await _upsert_price_point(conn, pid, post)
    await conn.commit()
    return ids


async def _upsert_price_point(conn, post_id: int, post: RawPost) -> None:
    offer = parse_title(post.title)
    if not offer.price or not offer.product_key:
        return
    observed = to_iso(post.posted_at) or utcnow_iso()
    await conn.execute(
        """
        INSERT INTO price_points(product_key, price, unit_price, seller, source, observed_at, post_id)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, post_id) DO UPDATE SET
            product_key=excluded.product_key,
            price=excluded.price,
            unit_price=excluded.unit_price,
            seller=excluded.seller,
            observed_at=excluded.observed_at
        """,
        (
            offer.product_key,
            offer.price,
            offer.unit_price,
            offer.seller,
            post.source,
            observed,
            post_id,
        ),
    )


async def rebuild_recent_deals(conn, hours: int = RECENT_DEAL_HOURS) -> int:
    cur = await conn.execute(
        """
        SELECT * FROM posts
        WHERE posted_at IS NULL OR posted_at >= datetime('now', ?)
        ORDER BY COALESCE(posted_at, collected_at) DESC
        """,
        (f"-{hours} hours",),
    )
    rows = await cur.fetchall()
    count = 0
    for row in rows:
        await upsert_deal_from_post(conn, dict(row))
        count += 1
    await conn.commit()
    return count


async def upsert_deal_from_post(conn, post_row: dict) -> int | None:
    offer = parse_title(post_row["title"])
    if not offer.product_key or not offer.price:
        return None

    cur = await conn.execute(
        """
        SELECT * FROM deals
        WHERE last_seen_at >= datetime('now', '-24 hours')
        ORDER BY last_seen_at DESC
        LIMIT 400
        """
    )
    recent = [dict(r) for r in await cur.fetchall()]
    match = None
    for existing in recent:
        existing["tokens"] = set((existing.get("product_key") or "").split("|"))
        if should_merge(offer, existing):
            match = existing
            break

    source_count = 1
    last_scored_at = None
    last_scored_price = None
    if match:
        cur = await conn.execute(
            "SELECT COUNT(DISTINCT p.source) AS c FROM deal_posts dp JOIN posts p ON p.id=dp.post_id WHERE dp.deal_id=?",
            (match["id"],),
        )
        source_count = int((await cur.fetchone())["c"] or 1)
        if match.get("last_scored_at"):
            try:
                last_scored_at = datetime.fromisoformat(match["last_scored_at"])
            except ValueError:
                last_scored_at = None
        last_scored_price = match.get("last_scored_price")

    if NAVER_SEED_ENABLED:
        await seed_baseline_if_needed(conn, offer)

    prices = await _load_prices(conn, offer)
    baseline = compute_baseline(prices)
    result = score_offer(
        offer,
        baseline,
        source_count=source_count + (0 if match else 0),
        votes=int(post_row.get("votes") or 0),
        last_scored_at=last_scored_at,
        last_scored_price=last_scored_price,
    )

    now = utcnow_iso()
    posted = post_row.get("posted_at") or now
    mall_url = post_row.get("mall_url") or extract_mall_url(
        post_row.get("body"), post_row.get("title"), post_row.get("raw_json")
    )
    thumbnail_url = post_row.get("thumbnail_url")
    category = classify(offer.product_name, offer.seller, _source_category(post_row))
    if match:
        deal_id = match["id"]
        new_price = offer.price if offer.price is not None else match["price"]
        scored_at = match.get("last_scored_at")
        scored_price = match.get("last_scored_price")
        if not result.suppress:
            scored_at = now
            scored_price = offer.price
        src_cur = await conn.execute(
            "SELECT GROUP_CONCAT(DISTINCT p.source) AS sources FROM deal_posts dp "
            "JOIN posts p ON p.id=dp.post_id WHERE dp.deal_id=?",
            (deal_id,),
        )
        src_row = await src_cur.fetchone()
        existing_sources = (src_row["sources"] if src_row else None) or ""
        take_display = prefers_non_ppomppu(post_row.get("source"), existing_sources)
        display_name = offer.product_name or match["product_name"]
        display_url = post_row["url"]
        display_seller = offer.seller
        if not take_display:
            display_name = match.get("product_name") or display_name
            display_url = match.get("deal_url") or display_url
            display_seller = match.get("seller") or display_seller
        await conn.execute(
            """
            UPDATE deals SET
                product_name=?,
                seller=COALESCE(?, seller),
                price=?,
                shipping_fee=?,
                unit_price=?,
                deal_url=?,
                mall_url=COALESCE(?, mall_url),
                thumbnail_url=COALESCE(?, thumbnail_url),
                last_seen_at=?,
                baseline_price=?,
                min_price=?,
                sample_count=?,
                discount_rate=?,
                score=?,
                grade=?,
                status=?,
                last_scored_at=?,
                last_scored_price=?,
                category=?
            WHERE id=?
            """,
            (
                display_name,
                display_seller,
                new_price,
                offer.shipping_fee,
                offer.unit_price,
                display_url,
                mall_url,
                thumbnail_url,
                now,
                baseline.median,
                baseline.minimum,
                baseline.sample_count,
                result.discount,
                result.score,
                result.grade,
                result.status,
                scored_at,
                scored_price,
                category,
                deal_id,
            ),
        )
    else:
        cur = await conn.execute(
            """
            INSERT INTO deals(
                product_key, product_name, seller, price, shipping_fee, unit_price,
                deal_url, mall_url, thumbnail_url, first_seen_at, last_seen_at, baseline_price, min_price,
                sample_count, discount_rate, score, grade, status,
                last_scored_at, last_scored_price, category
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                offer.product_key,
                offer.product_name,
                offer.seller,
                offer.price,
                offer.shipping_fee,
                offer.unit_price,
                post_row["url"],
                mall_url,
                thumbnail_url,
                posted,
                now,
                baseline.median,
                baseline.minimum,
                baseline.sample_count,
                result.discount,
                result.score,
                result.grade,
                result.status,
                now,
                offer.price,
                category,
            ),
        )
        deal_id = cur.lastrowid

    await conn.execute(
        "INSERT OR IGNORE INTO deal_posts(deal_id, post_id) VALUES(?, ?)",
        (deal_id, post_row["id"]),
    )
    return deal_id


async def _load_prices(conn, offer) -> list[tuple[str, int]]:
    qty = (offer.quantity.label or "").lower()
    if qty:
        cur = await conn.execute(
            """
            SELECT product_key, observed_at, price FROM price_points
            WHERE observed_at >= datetime('now', ?)
              AND (product_key = ? OR product_key LIKE ?)
            """,
            (f"-{BASELINE_DAYS} days", offer.product_key, f"%{qty}%"),
        )
    else:
        cur = await conn.execute(
            """
            SELECT product_key, observed_at, price FROM price_points
            WHERE product_key=? AND observed_at >= datetime('now', ?)
            """,
            (offer.product_key, f"-{BASELINE_DAYS} days"),
        )
    prices: list[tuple[str, int]] = []
    for row in await cur.fetchall():
        other = set((row["product_key"] or "").split("|"))
        if row["product_key"] == offer.product_key or jaccard(offer.tokens, other) >= 0.6:
            prices.append((row["observed_at"], row["price"]))
    return prices


async def fetch_deal_card(conn, deal_id: int) -> dict | None:
    cur = await conn.execute(
        """
        SELECT d.*, GROUP_CONCAT(DISTINCT p.source) AS sources,
               (
                 SELECT p2.source FROM deal_posts dp2
                 JOIN posts p2 ON p2.id = dp2.post_id
                 WHERE dp2.deal_id = d.id
                 ORDER BY p2.collected_at ASC, p2.id ASC
                 LIMIT 1
               ) AS first_source
        FROM deals d
        LEFT JOIN deal_posts dp ON dp.deal_id=d.id
        LEFT JOIN posts p ON p.id=dp.post_id
        WHERE d.id=?
        GROUP BY d.id
        """,
        (deal_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def collect_and_process(conn, sources, client) -> dict:
    summary = {"sources": {}, "posts": 0, "new_posts": 0, "errors": [], "new_deals": []}
    from app.db import upsert_post

    for source in sources:
        try:
            posts = await source.fetch_latest(client)
            new_count = 0
            for post in posts:
                pid, inserted = await upsert_post(conn, post_to_row(post))
                summary["posts"] += 1

                cheap = enrich_from_list_body(post.body)
                mall_url = cheap.mall_url or extract_mall_url(post.body, post.title)
                thumbnail_url = (
                    cheap.thumbnail_url
                    or (post.extra or {}).get("thumbnail_url")
                )

                if mall_url or thumbnail_url:
                    await upsert_post(
                        conn,
                        post_to_row(post, thumbnail_url=thumbnail_url),
                    )
                    await conn.execute(
                        """
                        UPDATE deals
                        SET mall_url=CASE
                                WHEN ? IS NOT NULL THEN ?
                                ELSE mall_url
                            END,
                            thumbnail_url=COALESCE(?, thumbnail_url)
                        WHERE id IN (SELECT deal_id FROM deal_posts WHERE post_id=?)
                        """,
                        (mall_url, mall_url, thumbnail_url, pid),
                    )

                if not inserted:
                    continue

                new_count += 1
                await _upsert_price_point(conn, pid, post)
                deal_id = await upsert_deal_from_post(
                    conn,
                    {
                        "id": pid,
                        "title": post.title,
                        "url": post.url,
                        "body": post.body,
                        "votes": post.votes,
                        "posted_at": to_iso(post.posted_at) or utcnow_iso(),
                        "mall_url": mall_url,
                        "thumbnail_url": thumbnail_url,
                    },
                )
                if deal_id:
                    card = await fetch_deal_card(conn, deal_id)
                    if card:
                        summary["new_deals"].append(card)
            summary["sources"][source.name] = {
                "fetched": len(posts),
                "new": new_count,
                "error": None,
            }
            summary["new_posts"] += new_count
        except Exception as exc:  # noqa: BLE001
            log.exception("source %s failed", source.name)
            detail = f"{type(exc).__name__}: {exc}".strip()
            summary["errors"].append(f"{source.name}: {detail}")
            summary["sources"][source.name] = {
                "fetched": 0,
                "new": 0,
                "error": detail,
            }
    now = utcnow_iso()
    async with _collect_meta_lock:
        await set_meta(conn, "last_collect_at", now)
        batch = {
            "at": now,
            "sources": summary["sources"],
            "posts": summary["posts"],
            "new_posts": summary["new_posts"],
            "errors": summary["errors"],
            "new_deal_count": len(summary["new_deals"]),
        }
        await set_meta(conn, "last_collect_summary", json.dumps(batch, ensure_ascii=False))
        prev_raw = await get_meta(conn, "last_collect_by_source")
        by_source: dict = {}
        if prev_raw:
            try:
                by_source = json.loads(prev_raw)
            except json.JSONDecodeError:
                by_source = {}
        for name, info in summary["sources"].items():
            by_source[name] = {**info, "at": now}
        await set_meta(conn, "last_collect_by_source", json.dumps(by_source, ensure_ascii=False))
        await conn.commit()
    try:
        from app.engine.alerts import dispatch_alerts

        summary["alerts"] = await dispatch_alerts(conn, client, summary.get("new_deals") or [])
        await conn.commit()
    except Exception:
        log.exception("alert dispatch failed")
        summary["alerts"] = {"error": "dispatch failed"}
    return summary
