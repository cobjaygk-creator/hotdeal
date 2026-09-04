from __future__ import annotations

_SORTS = {
    "fee": "COALESCE(discount_fee, original_fee) ASC, signup_count DESC",
    "popular": "signup_count DESC, COALESCE(discount_fee, original_fee) ASC",
    "data": "data_unlimited DESC, data_gb DESC, COALESCE(discount_fee, original_fee) ASC",
}


async def list_event_plans(conn, *, sort: str = "fee", mno: str | None = None,
                           network: str | None = None) -> list[dict]:
    where = ["active=1"]
    params: list = []
    if mno:
        where.append("mno=?")
        params.append(mno)
    if network:
        where.append("network=?")
        params.append(network)
    order = _SORTS.get(sort, _SORTS["fee"])
    cur = await conn.execute(
        f"SELECT * FROM mvno_plans WHERE {' AND '.join(where)} ORDER BY {order} LIMIT 200",
        params,
    )
    return [dict(r) for r in await cur.fetchall()]


async def mno_options(conn) -> list[str]:
    cur = await conn.execute(
        "SELECT DISTINCT mno FROM mvno_plans WHERE active=1 AND mno IS NOT NULL ORDER BY mno"
    )
    return [r[0] for r in await cur.fetchall()]
