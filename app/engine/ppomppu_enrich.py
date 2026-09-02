"""Background ppomppu mall-url enrich via optional residential proxy.

hotdeal.zip-style flow: fetch community detail HTML → parse buy URL → store.
Runs outside the 60s RSS tick so collect stays fast.
"""
from __future__ import annotations

import json
import logging

from app.config import PPOMPPU_ENRICH_BATCH, PPOMPPU_PROXY_URL
from app.db import set_meta, utcnow_iso
from app.sources.detail import enrich_post

log = logging.getLogger(__name__)


async def enrich_missing_ppomppu_malls(conn, client, *, limit: int | None = None) -> dict:
    """Fill mall_url for recent ppomppu deals that still lack a buy link."""
    if not PPOMPPU_PROXY_URL:
        return {
            "skipped": True,
            "reason": "PPOMPPU_PROXY_URL not set",
            "attempted": 0,
            "filled": 0,
            "blocked": 0,
            "no_link": 0,
        }

    batch = limit if limit is not None else PPOMPPU_ENRICH_BATCH
    batch = max(1, min(50, batch))
    cur = await conn.execute(
        """
        SELECT d.id AS deal_id, p.id AS post_id, p.url AS post_url
        FROM deals d
        JOIN deal_posts dp ON dp.deal_id = d.id
        JOIN posts p ON p.id = dp.post_id
        WHERE p.source = 'ppomppu'
          AND (d.mall_url IS NULL OR TRIM(d.mall_url) = '')
          AND p.url IS NOT NULL
        ORDER BY d.last_seen_at DESC
        LIMIT ?
        """,
        (batch,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    filled = 0
    blocked = 0  # detail page refused (403 / soft-block) -> exit IP quality
    no_link = 0  # detail fetched fine but the post has no buy link
    errors = 0
    consecutive_blocked = 0
    for row in rows:
        try:
            detail = await enrich_post(client, "ppomppu", row["post_url"])
        except Exception:  # noqa: BLE001
            log.exception("ppomppu enrich failed deal=%s", row["deal_id"])
            errors += 1
            continue
        if not detail.mall_url:
            if getattr(detail, "blocked", False):
                blocked += 1
                consecutive_blocked += 1
                # Exit IP is being soft-blocked: stop burning the batch so the
                # next tick can retry (rotating proxies may hand us a fresh IP).
                if consecutive_blocked >= 3 and filled == 0:
                    break
            else:
                no_link += 1
                consecutive_blocked = 0
            continue
        consecutive_blocked = 0
        await conn.execute(
            """
            UPDATE deals
            SET mall_url = ?,
                thumbnail_url = COALESCE(?, thumbnail_url)
            WHERE id = ?
            """,
            (detail.mall_url, detail.thumbnail_url, row["deal_id"]),
        )
        if detail.thumbnail_url:
            await conn.execute(
                """
                UPDATE posts
                SET thumbnail_url = COALESCE(?, thumbnail_url)
                WHERE id = ?
                """,
                (detail.thumbnail_url, row["post_id"]),
            )
        filled += 1

    await conn.commit()
    summary = {
        "skipped": False,
        "proxy": True,
        "attempted": len(rows),
        "filled": filled,
        "blocked": blocked,
        "no_link": no_link,
        "errors": errors,
        "at": utcnow_iso(),
    }
    await set_meta(conn, "last_ppomppu_mall_enrich", json.dumps(summary, ensure_ascii=False))
    log.info(
        "ppomppu mall enrich attempted=%s filled=%s blocked=%s no_link=%s errors=%s",
        len(rows),
        filled,
        blocked,
        no_link,
        errors,
    )
    return summary
