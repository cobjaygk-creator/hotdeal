import pytest

from app.engine.points import award, balance, checkin, history


async def _fresh_conn(tmp_path):
    import aiosqlite

    from app.db import SCHEMA

    db_path = tmp_path / "points.db"
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.execute(
        "INSERT INTO users(id, display_name, created_at, last_login_at) VALUES (1, 'tester', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
    )
    await conn.commit()
    return conn


@pytest.mark.asyncio
async def test_award_accumulates_balance(tmp_path):
    conn = await _fresh_conn(tmp_path)
    assert await award(conn, 1, 500, "signup_bonus") == 500
    assert await award(conn, 1, 10, "daily_checkin") == 510
    assert await balance(conn, 1) == 510
    rows = await history(conn, 1)
    assert [r["reason"] for r in rows] == ["daily_checkin", "signup_bonus"]
    await conn.close()


@pytest.mark.asyncio
async def test_checkin_is_once_per_day(tmp_path):
    conn = await _fresh_conn(tmp_path)
    first = await checkin(conn, 1)
    assert first == {"already": False, "balance": 10, "earned": 10}
    second = await checkin(conn, 1)
    assert second == {"already": True, "balance": 10}
    await conn.close()


@pytest.mark.asyncio
async def test_balance_zero_for_unknown_user(tmp_path):
    conn = await _fresh_conn(tmp_path)
    assert await balance(conn, 999) == 0
    await conn.close()
