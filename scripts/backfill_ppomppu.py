"""Ppomppu board backfill. Respects 1s+ delay via PoliteClient. Resumable."""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config import BASELINE_DAYS
from app.db import connect, get_meta, set_meta, utcnow_iso
from app.http_client import PoliteClient
from app.pipeline import ingest_posts, rebuild_recent_deals
from app.sources.ppomppu import PpomppuSource
from app.util.timeparse import to_iso

log = logging.getLogger("backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def run(days: int, max_pages: int, start_page: int | None) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    conn = await connect()
    client = PoliteClient()
    source = PpomppuSource()
    page = start_page
    if page is None:
        saved = await get_meta(conn, "ppomppu_backfill_page")
        page = int(saved) if saved else 1

    oldest: datetime | None = None
    total = 0
    try:
        while page <= max_pages:
            log.info("page %s", page)
            posts = await source.fetch_page(client, page)
            if not posts:
                log.info("empty page, stop")
                break
            total += len(posts)
            await ingest_posts(conn, posts)
            await set_meta(conn, "ppomppu_backfill_page", str(page + 1))
            await conn.commit()
            dated = [p.posted_at for p in posts if p.posted_at]
            if dated:
                oldest = min(dated)
                log.info("oldest on page %s", to_iso(oldest))
                if oldest.tzinfo is None:
                    oldest = oldest.replace(tzinfo=timezone.utc)
                if oldest < cutoff:
                    log.info("reached cutoff %s", cutoff.date())
                    break
            page += 1
        rebuilt = await rebuild_recent_deals(conn)
        await set_meta(conn, "last_backfill_at", utcnow_iso())
        await conn.commit()
        log.info("ingested ~%s posts, rebuilt %s recent deals", total, rebuilt)
    finally:
        await client.aclose()
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=BASELINE_DAYS)
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--start-page", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.days, args.max_pages, args.start_page))


if __name__ == "__main__":
    main()
