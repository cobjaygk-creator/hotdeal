import asyncio

from app.db import connect
from app.pipeline import rebuild_recent_deals


async def main():
    conn = await connect()
    try:
        n = await rebuild_recent_deals(conn, hours=72)
        print("rebuilt", n)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
