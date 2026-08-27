from __future__ import annotations

from collections import defaultdict

from app.db import set_meta, upsert_family_sale, utcnow_iso
from app.family.dealink import DealinkSource
from app.family.eomisae import EomisaeFamilySource
from app.family.parse import decode_sale_row, normalize_sale, should_merge
from app.http_client import PoliteClient


def family_sources():
    return [DealinkSource(), EomisaeFamilySource()]


async def collect_family_sales(conn, client: PoliteClient) -> dict:
    summary = {"sources": {}, "new": 0, "updated": 0}
    for source in family_sources():
        try:
            raws = await source.fetch_latest(client)
        except Exception as exc:
            summary["sources"][source.name] = {"error": str(exc), "count": 0}
            continue
        inserted = 0
        updated = 0
        for raw in raws:
            sale = normalize_sale(raw)
            _id, is_new = await upsert_family_sale(conn, sale)
            if is_new:
                inserted += 1
            else:
                updated += 1
        await conn.commit()
        summary["sources"][source.name] = {"count": len(raws), "new": inserted, "updated": updated}
        summary["new"] += inserted
        summary["updated"] += updated
    await merge_family_groups(conn)
    await set_meta(conn, "last_family_collect_at", utcnow_iso())
    await conn.commit()
    return summary


async def merge_family_groups(conn) -> None:
    cur = await conn.execute(
        "SELECT id, brand_names, start_date, end_date FROM family_sales WHERE start_date IS NOT NULL"
    )
    rows = [decode_sale_row(dict(r)) for r in await cur.fetchall()]
    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            if should_merge(a, b):
                union(a["id"], b["id"])
    groups: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        groups[find(r["id"])].append(r["id"])
    for gid, ids in groups.items():
        for sid in ids:
            await conn.execute("UPDATE family_sales SET group_id=? WHERE id=?", (gid, sid))
