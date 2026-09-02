from __future__ import annotations

from app.amazon_jp.mottoku import MottokuAmazonSource
from app.config import AMAZON_JP_ASSOCIATE_TAG
from app.db import set_meta, upsert_amazon_jp_deal, utcnow_iso
from app.http_client import PoliteClient


def amazon_product_url(asin: str) -> str:
    url = f"https://www.amazon.co.jp/dp/{asin}"
    tag = (AMAZON_JP_ASSOCIATE_TAG or "").strip()
    if tag:
        url += f"?tag={tag}"
    return url


def amazon_jp_sources():
    return [MottokuAmazonSource()]


async def collect_amazon_jp(conn, client: PoliteClient) -> dict:
    started = utcnow_iso()
    summary = {"sources": {}, "new": 0, "updated": 0, "count": 0}
    asins: list[str] = []
    for source in amazon_jp_sources():
        try:
            raws = await source.fetch_latest(client)
        except Exception as exc:
            summary["sources"][source.name] = {"error": str(exc), "count": 0}
            continue
        inserted = 0
        updated = 0
        for raw in raws:
            row = {
                "asin": raw.asin,
                "title": raw.title,
                "yen_price": raw.yen_price,
                "original_yen": raw.original_yen,
                "discount_rate": raw.discount_rate,
                "image_url": raw.image_url,
                "amazon_url": amazon_product_url(raw.asin),
                "source": raw.source,
                "source_url": raw.source_url,
                "source_updated_at": raw.source_updated_at,
                "active": 1,
            }
            _id, is_new = await upsert_amazon_jp_deal(conn, row)
            asins.append(raw.asin)
            if is_new:
                inserted += 1
            else:
                updated += 1
        await conn.commit()
        summary["sources"][source.name] = {
            "count": len(raws),
            "new": inserted,
            "updated": updated,
        }
        summary["new"] += inserted
        summary["updated"] += updated
        summary["count"] += len(raws)

    if asins:
        placeholders = ",".join("?" * len(asins))
        await conn.execute(
            f"UPDATE amazon_jp_deals SET active=0 WHERE asin NOT IN ({placeholders}) AND last_seen_at < ?",
            [*asins, started],
        )
    await set_meta(conn, "last_amazon_jp_collect_at", utcnow_iso())
    await conn.commit()
    return summary
