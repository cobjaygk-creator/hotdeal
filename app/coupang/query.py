from __future__ import annotations


CATEGORY_LABELS = {
    "1001": "식품", "1002": "생활", "1010": "PC", "1011": "가전",
    "1012": "의류", "1013": "유아", "1014": "스포츠", "1015": "여행",
}


async def list_coupang_deals(db, limit: int = 120, category_id: str | None = None) -> list[dict]:
    where = "active=1"
    params: list = []
    if category_id:
        where += " AND category_id=?"
        params.append(category_id)
    params.append(max(1, min(300, limit)))
    cur = await db.execute(
        f"""
        SELECT *, COALESCE(NULLIF(category_id, ''), '') AS category_key
        FROM coupang_deals
        WHERE {where}
        ORDER BY discount_rate DESC, last_seen_at DESC, id DESC
        LIMIT ?
        """,
        params,
    )
    rows = [dict(r) for r in await cur.fetchall()]
    for row in rows:
        row["category_name"] = CATEGORY_LABELS.get(str(row.get("category_id") or ""), "기타")
    return rows
