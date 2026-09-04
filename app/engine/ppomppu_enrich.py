"""Background mall-url enrich for every community source.

Fetch detail HTML → parse buy URL → store. Runs outside the collect tick.
Ppomppu (and other blocked hosts) use PPOMPPU_PROXY_URL when set.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from app.config import PPOMPPU_ENRICH_BATCH, PPOMPPU_PROXY_URL
from app.db import set_meta, utcnow_iso
from app.parse.links import prefers_mall
from app.sources.detail import enrich_post

log = logging.getLogger(__name__)


async def enrich_missing_ppomppu_malls(conn, client, *, limit: int | None = None) -> dict:
    """Fill mall_url for recent deals (all sources) that still lack a buy link."""
    batch = limit if limit is not None else PPOMPPU_ENRICH_BATCH
    batch = max(1, min(50, batch))
    cur = await conn.execute(
        """
        SELECT deal_id, post_id, post_url, source, mall_url FROM (
          SELECT d.id AS deal_id,
                 p.id AS post_id,
                 p.url AS post_url,
                 p.source AS source,
                 d.mall_url AS mall_url,
                 ROW_NUMBER() OVER (
                   PARTITION BY p.source
                   ORDER BY d.last_seen_at DESC
                 ) AS rn
          FROM deals d
          JOIN deal_posts dp ON dp.deal_id = d.id
          JOIN posts p ON p.id = dp.post_id
          WHERE (
                d.mall_url IS NULL
                OR TRIM(d.mall_url) = ''
                OR (
                  lower(d.mall_url) LIKE '%www.coupang.com/%'
                  AND lower(d.mall_url) NOT LIKE '%lptag=%'
                )
              )
            AND p.url IS NOT NULL
            AND p.id = (
              SELECT p2.id
              FROM deal_posts dp2
              JOIN posts p2 ON p2.id = dp2.post_id
              WHERE dp2.deal_id = d.id
                AND p2.url IS NOT NULL
              ORDER BY CASE WHEN p2.source = 'ppomppu' THEN 1 ELSE 0 END, p2.id
              LIMIT 1
            )
        )
        WHERE rn <= 6
        ORDER BY source, deal_id DESC
        LIMIT ?
        """,
        (batch,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    filled = 0
    blocked = 0
    no_link = 0
    errors = 0
    attempted = 0
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: {"filled": 0, "blocked": 0, "no_link": 0})
    consec_blocked: dict[str, int] = defaultdict(int)
    filled_by_source: dict[str, int] = defaultdict(int)
    skip_sources: set[str] = set()

    for row in rows:
        source = (row.get("source") or "").strip() or "ppomppu"
        if source in skip_sources:
            continue
        attempted += 1
        try:
            detail = await enrich_post(client, source, row["post_url"])
        except Exception:  # noqa: BLE001
            log.exception("mall enrich failed source=%s deal=%s", source, row["deal_id"])
            errors += 1
            continue
        if not detail.mall_url:
            if getattr(detail, "blocked", False):
                blocked += 1
                by_source[source]["blocked"] += 1
                consec_blocked[source] += 1
                if consec_blocked[source] >= 3 and filled_by_source[source] == 0:
                    skip_sources.add(source)
            else:
                no_link += 1
                by_source[source]["no_link"] += 1
                consec_blocked[source] = 0
            continue
        if not prefers_mall(detail.mall_url, row.get("mall_url")):
            continue
        consec_blocked[source] = 0
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
        filled_by_source[source] += 1
        by_source[source]["filled"] += 1

    await conn.commit()
    summary = {
        "skipped": False,
        "proxy": bool(PPOMPPU_PROXY_URL),
        "attempted": attempted,
        "filled": filled,
        "blocked": blocked,
        "no_link": no_link,
        "errors": errors,
        "by_source": dict(by_source),
        "at": utcnow_iso(),
    }
    await set_meta(conn, "last_ppomppu_mall_enrich", json.dumps(summary, ensure_ascii=False))
    log.info(
        "mall enrich attempted=%s filled=%s blocked=%s no_link=%s errors=%s sources=%s",
        attempted,
        filled,
        blocked,
        no_link,
        errors,
        dict(by_source),
    )
    return summary
