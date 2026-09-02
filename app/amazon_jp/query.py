from __future__ import annotations


async def list_amazon_jp_deals(db, limit: int = 120) -> list[dict]:
    cur = await db.execute(
        """
        SELECT * FROM amazon_jp_deals
        WHERE active=1
        ORDER BY discount_rate DESC, last_seen_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(r) for r in await cur.fetchall()]
