"""User points: earn/spend ledger + daily check-in.

MVP scope: earning (signup bonus, daily check-in), balance, and history only.
No redemption catalog yet — `/points` shows the balance/history and a "포인트샵
준비중" placeholder (see app/main.py's /points route).
"""
from __future__ import annotations

from app.db import utcnow_iso


async def award(conn, user_id: int, delta: int, reason: str) -> int:
    """Append a ledger row and update the running balance. Returns new balance."""
    now = utcnow_iso()
    await conn.execute(
        "INSERT INTO point_ledger(user_id, delta, reason, created_at) VALUES (?, ?, ?, ?)",
        (user_id, delta, reason, now),
    )
    await conn.execute(
        """
        INSERT INTO user_points(user_id, balance, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            balance = balance + excluded.balance,
            updated_at = excluded.updated_at
        """,
        (user_id, delta, now),
    )
    await conn.commit()
    return await balance(conn, user_id)


async def balance(conn, user_id: int) -> int:
    cur = await conn.execute("SELECT balance FROM user_points WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return int(row["balance"]) if row else 0


async def history(conn, user_id: int, limit: int = 50) -> list[dict]:
    cur = await conn.execute(
        "SELECT delta, reason, created_at FROM point_ledger WHERE user_id=? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(row) for row in await cur.fetchall()]


CHECKIN_REWARD = 10


async def checkin(conn, user_id: int) -> dict:
    """Award CHECKIN_REWARD once per KST calendar day. Idempotent via the
    UNIQUE(user_id, checkin_date) constraint on checkin_log."""
    today = utcnow_iso()[:10]
    now = utcnow_iso()
    cur = await conn.execute(
        "INSERT OR IGNORE INTO checkin_log(user_id, checkin_date, created_at) VALUES (?, ?, ?)",
        (user_id, today, now),
    )
    await conn.commit()
    already = cur.rowcount == 0
    if already:
        return {"already": True, "balance": await balance(conn, user_id)}
    new_balance = await award(conn, user_id, CHECKIN_REWARD, "daily_checkin")
    return {"already": False, "balance": new_balance, "earned": CHECKIN_REWARD}
