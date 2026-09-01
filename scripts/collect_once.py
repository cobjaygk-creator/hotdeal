import asyncio
import json
import sys

from app.config import ENABLE_COLLECT
from app.db import connect
from app.http_client import PoliteClient
from app.pipeline import collect_and_process
from app.sources.registry import get_sources


async def main():
    if not ENABLE_COLLECT:
        print("collect disabled; set ENABLE_COLLECT=1 to crawl from this machine", file=sys.stderr)
        raise SystemExit(1)
    conn = await connect()
    client = PoliteClient()
    try:
        summary = await collect_and_process(conn, get_sources(), client)
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    finally:
        await client.aclose()
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
