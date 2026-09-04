"""Background mall-url enrich for every community source.

Fetch detail HTML → parse buy URL → store. Runs outside the collect tick.
Ppomppu (and other blocked hosts) use PPOMPPU_PROXY_URL when set.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict

from app.config import PPOMPPU_ENRICH_BATCH, PPOMPPU_PROXY_URL
from app.db import set_meta, utcnow_iso
from app.engine.category import classify
from app.parse.links import prefers_mall
from app.parse.sanitize_html import prefers_body_html
from app.parse.title import parse_title
from app.pipeline import fetch_deal_card
from app.sources.detail import enrich_post

log = logging.getLogger(__name__)

_ENRICH_TIMEOUT_SEC = 18.0
# Quasarzone list sometimes attaches this ancient shared placeholder as data-preview.
_STALE_QZ_THUMB = "%dc9345db51f5b6aa0e363ed2cfbe9358%"
# Don't re-fetch a deal's detail page (a proxied request) more than once per
# this window during the background sweep — a deal that can't be enriched was
# re-tried every tick, which was a big chunk of the residential-proxy GB.
_ATTEMPT_COOLDOWN_SEC = 45 * 60
_last_attempt: dict[int, float] = {}


def _cooldown_ok(deal_id: int) -> bool:
    now = time.time()
    if now - _last_attempt.get(deal_id, 0.0) < _ATTEMPT_COOLDOWN_SEC:
        return False
    _last_attempt[deal_id] = now
    if len(_last_attempt) > 5000:  # prune
        cutoff = now - _ATTEMPT_COOLDOWN_SEC
        for k in [k for k, v in _last_attempt.items() if v < cutoff]:
            _last_attempt.pop(k, None)
    return True


async def enrich_missing_ppomppu_malls(
    conn,
    client,
    *,
    limit: int | None = None,
    deal_ids: list[int] | None = None,
) -> dict:
    """Fill mall_url for recent deals (all sources) that still lack a buy link."""
    batch = limit if limit is not None else PPOMPPU_ENRICH_BATCH
    batch = max(1, min(50, batch))
    extra_sql = ""
    params: list = []
    if deal_ids:
        wanted = [int(x) for x in deal_ids if x]
        if not wanted:
            return {
                "skipped": False,
                "proxy": bool(PPOMPPU_PROXY_URL),
                "attempted": 0,
                "filled": 0,
                "blocked": 0,
                "no_link": 0,
                "errors": 0,
                "by_source": {},
                "cards": [],
                "at": utcnow_iso(),
            }
        # Explicit ids: re-fetch even when mall_url is already set (title/body repair).
        extra_sql = f" AND d.id IN ({','.join('?' * len(wanted))})"
        params.extend(wanted)
        mall_filter = "1=1"
    else:
        mall_filter = f"""(
                d.mall_url IS NULL
                OR TRIM(d.mall_url) = ''
                OR (
                  lower(d.mall_url) LIKE '%www.coupang.com/%'
                  AND lower(d.mall_url) NOT LIKE '%lptag=%'
                  AND lower(d.mall_url) NOT LIKE '%/vp/products/%'
                )
                OR lower(d.mall_url) LIKE '%link.coupang.com/%'
                OR lower(d.mall_url) LIKE '%coupa.ng/%'
                OR lower(d.mall_url) LIKE '%saedu.naver.com%'
                OR lower(d.mall_url) LIKE '%searchad.naver.com%'
                OR lower(d.mall_url) LIKE '%nid.naver.com%'
                OR lower(d.mall_url) LIKE '%api.fixer.io%'
                OR lower(d.mall_url) LIKE '%dajooda.com%'
                OR lower(d.mall_url) LIKE '%nhnace.com%'
                OR lower(d.mall_url) LIKE '%acecounter.com%'
                OR lower(d.mall_url) LIKE '%/today_deals%'
                OR lower(d.mall_url) LIKE '%oy.run/%'
                OR lower(d.mall_url) LIKE '%dbada.kr/%'
                OR lower(d.mall_url) LIKE '%makeshortlink%'
                OR lower(d.mall_url) LIKE '%/func.php%'
                OR lower(d.mall_url) LIKE '%.js?%'
                OR lower(d.mall_url) LIKE '%.js'
                OR lower(d.mall_url) LIKE '%/_next/static/%'
                OR lower(d.mall_url) LIKE 'http%://cf-static.%'
                OR lower(d.mall_url) LIKE 'http%://static.%'
                OR (
                  p.source = 'quasarzone'
                  AND d.thumbnail_url LIKE '{_STALE_QZ_THUMB}'
                )
                OR p.body_html IS NULL
                OR TRIM(p.body_html) = ''
                OR (
                  -- Link-only / chrome body left by a wrong .xe_content hit.
                  lower(p.body_html) LIKE '%<a %'
                  AND lower(p.body_html) NOT LIKE '%<img %'
                  AND length(p.body_html) < 400
                )
              )"""
    params.append(batch)
    cur = await conn.execute(
        f"""
        SELECT deal_id, post_id, post_url, source, mall_url, body_html FROM (
          SELECT d.id AS deal_id,
                 p.id AS post_id,
                 p.url AS post_url,
                 p.source AS source,
                 d.mall_url AS mall_url,
                 p.body_html AS body_html,
                 ROW_NUMBER() OVER (
                   PARTITION BY p.source
                   ORDER BY d.last_seen_at DESC
                 ) AS rn
          FROM deals d
          JOIN deal_posts dp ON dp.deal_id = d.id
          JOIN posts p ON p.id = dp.post_id
          WHERE {mall_filter}
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
            {extra_sql}
        )
        {"WHERE 1=1" if deal_ids else "WHERE rn <= 8"}
        ORDER BY source, deal_id DESC
        LIMIT ?
        """,
        params,
    )
    rows = [dict(r) for r in await cur.fetchall()]
    if not deal_ids:  # background sweep: honour the per-deal cooldown
        rows = [r for r in rows if _cooldown_ok(int(r["deal_id"]))]
    filled = 0
    blocked = 0
    no_link = 0
    errors = 0
    attempted = 0
    by_source: dict[str, dict[str, int]] = defaultdict(
        lambda: {"filled": 0, "blocked": 0, "no_link": 0}
    )
    filled_ids: list[int] = []
    write_lock = asyncio.Lock()

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("source") or "").strip() or "ppomppu"].append(row)

    async def _run_source(source: str, items: list[dict]) -> None:
        nonlocal filled, blocked, no_link, errors, attempted
        consec_blocked = 0
        filled_here = 0
        for row in items:
            if consec_blocked >= 3 and filled_here == 0:
                break
            attempted += 1
            try:
                detail = await asyncio.wait_for(
                    enrich_post(client, source, row["post_url"]),
                    timeout=_ENRICH_TIMEOUT_SEC,
                )
            except TimeoutError:
                errors += 1
                continue
            except Exception:  # noqa: BLE001
                log.exception("mall enrich failed source=%s deal=%s", source, row["deal_id"])
                errors += 1
                continue

            mall_url = getattr(detail, "mall_url", None)
            title_txt = (getattr(detail, "title", None) or "").strip()
            thumb = getattr(detail, "thumbnail_url", None)
            body_html = (getattr(detail, "body_html", None) or "").strip() or None
            mall_better = prefers_mall(mall_url, row.get("mall_url"))
            title_update = len(title_txt) >= 4
            thumb_update = bool(thumb)
            body_update = prefers_body_html(body_html, row.get("body_html"))

            if not mall_url:
                if getattr(detail, "blocked", False):
                    blocked += 1
                    by_source[source]["blocked"] += 1
                    consec_blocked += 1
                else:
                    no_link += 1
                    by_source[source]["no_link"] += 1
                    consec_blocked = 0
                if not title_update and not thumb_update and not body_update:
                    continue
            elif not mall_better and not title_update and not thumb_update and not body_update:
                continue
            else:
                consec_blocked = 0

            async with write_lock:
                if mall_better and mall_url:
                    await conn.execute(
                        """
                        UPDATE deals
                        SET mall_url = ?,
                            thumbnail_url = COALESCE(?, thumbnail_url)
                        WHERE id = ?
                        """,
                        (mall_url, thumb, row["deal_id"]),
                    )
                elif thumb_update:
                    await conn.execute(
                        """
                        UPDATE deals
                        SET thumbnail_url = COALESCE(?, thumbnail_url)
                        WHERE id = ?
                        """,
                        (thumb, row["deal_id"]),
                    )
                if thumb_update:
                    await conn.execute(
                        """
                        UPDATE posts
                        SET thumbnail_url = COALESCE(?, thumbnail_url)
                        WHERE id = ?
                        """,
                        (thumb, row["post_id"]),
                    )
                if body_update:
                    await conn.execute(
                        "UPDATE posts SET body_html = ? WHERE id = ?",
                        (body_html, row["post_id"]),
                    )
                # Detail title wins when the list row was mismatched / truncated.
                if title_update:
                    await conn.execute(
                        "UPDATE posts SET title=? WHERE id=?",
                        (title_txt, row["post_id"]),
                    )
                    offer = parse_title(title_txt)
                    name = offer.product_name or title_txt
                    cat = classify(name, offer.seller)
                    if offer.product_key:
                        await conn.execute(
                            """
                            UPDATE deals
                            SET product_name=?,
                                product_key=?,
                                seller=COALESCE(?, seller),
                                price=COALESCE(?, price),
                                category=COALESCE(?, category)
                            WHERE id=?
                            """,
                            (
                                name,
                                offer.product_key,
                                offer.seller,
                                offer.price,
                                cat,
                                row["deal_id"],
                            ),
                        )
                    else:
                        await conn.execute(
                            """
                            UPDATE deals
                            SET product_name=?,
                                seller=COALESCE(?, seller),
                                category=COALESCE(?, category)
                            WHERE id=?
                            """,
                            (name, offer.seller, cat, row["deal_id"]),
                        )
            filled += 1
            filled_here += 1
            filled_ids.append(int(row["deal_id"]))
            by_source[source]["filled"] += 1

    if grouped:
        await asyncio.gather(*(_run_source(src, items) for src, items in grouped.items()))

    await conn.commit()
    cards = []
    try:
        for deal_id in filled_ids:
            card = await fetch_deal_card(conn, deal_id)
            if card:
                cards.append(card)
    except Exception:
        log.debug("enrich card fetch skipped", exc_info=True)
    summary = {
        "skipped": False,
        "proxy": bool(PPOMPPU_PROXY_URL),
        "attempted": attempted,
        "filled": filled,
        "blocked": blocked,
        "no_link": no_link,
        "errors": errors,
        "by_source": dict(by_source),
        "cards": cards,
        "at": utcnow_iso(),
    }
    meta = {k: v for k, v in summary.items() if k != "cards"}
    await set_meta(conn, "last_ppomppu_mall_enrich", json.dumps(meta, ensure_ascii=False))
    await conn.commit()
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
