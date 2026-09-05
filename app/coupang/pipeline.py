from __future__ import annotations

from app.coupang.api import create_deeplinks
from app.coupang.golden_box import fetch_golden_box
from app.db import set_meta, upsert_coupang_deal, utcnow_iso

# Broad top-level Coupang category ids. Adjust once the live API is
# reachable and the useful categories are known.
CATEGORY_IDS = ["1001", "1002", "1010", "1011", "1012", "1013", "1014", "1015"]


async def collect_coupang(conn) -> dict:
    started = utcnow_iso()
    summary = {"new": 0, "updated": 0, "count": 0, "errors": []}
    raws = []
    for cat in CATEGORY_IDS:
        try:
            raws.extend(await fetch_golden_box(cat))
        except Exception as exc:
            summary["errors"].append(f"{cat}: {exc}")

    by_url = {r.product_url: r for r in raws}
    deeplinks = {}
    try:
        deeplinks = await create_deeplinks(list(by_url.keys()))
    except Exception as exc:
        summary["errors"].append(f"deeplink: {exc}")

    seen: list[str] = []
    for url, raw in by_url.items():
        row = {
            "product_id": raw.product_id,
            "title": raw.title,
            "price": raw.price,
            "original_price": raw.original_price,
            "discount_rate": raw.discount_rate,
            "image_url": raw.image_url,
            "buy_url": deeplinks.get(url, url),
            "category_id": raw.category_id,
            "active": 1,
        }
        _id, is_new = await upsert_coupang_deal(conn, row)
        seen.append(raw.product_id)
        if is_new:
            summary["new"] += 1
        else:
            summary["updated"] += 1
    summary["count"] = len(seen)

    if seen:
        placeholders = ",".join("?" * len(seen))
        await conn.execute(
            f"UPDATE coupang_deals SET active=0 WHERE product_id NOT IN ({placeholders}) AND last_seen_at < ?",
            [*seen, started],
        )
    await set_meta(conn, "last_coupang_collect_at", utcnow_iso())
    await conn.commit()
    return summary
