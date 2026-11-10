import pytest

from app.engine.auth import (
    authenticate_local,
    ensure_local_admin,
    hash_password,
    is_admin_user,
    set_nickname,
    verify_password,
)


def test_password_hash_roundtrip():
    encoded = hash_password("secret-pass")
    assert verify_password("secret-pass", encoded)
    assert not verify_password("wrong", encoded)


@pytest.mark.asyncio
async def test_ensure_and_authenticate_admin(tmp_path, monkeypatch):
    import aiosqlite

    from app.db import SCHEMA

    monkeypatch.setattr("app.engine.auth.ADMIN_USERNAME", "admin")
    monkeypatch.setattr("app.engine.auth.ADMIN_PASSWORD", "test-admin-pass")
    db_path = tmp_path / "auth.db"
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()

    await ensure_local_admin(conn)
    user = await authenticate_local(conn, "admin", "test-admin-pass")
    assert user is not None
    assert is_admin_user(user)
    assert await authenticate_local(conn, "admin", "nope") is None
    await conn.close()


@pytest.mark.asyncio
async def test_set_nickname_validates_and_blocks_duplicates(tmp_path):
    import aiosqlite

    from app.db import SCHEMA

    conn = await aiosqlite.connect(tmp_path / "nick.db")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.execute(
        "INSERT INTO users(id, display_name, created_at, last_login_at) VALUES"
        " (1, 'a', '2026-01-01 00:00:00', '2026-01-01 00:00:00'),"
        " (2, 'b', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
    )
    await conn.commit()

    assert await set_nickname(conn, 1, "핫딜왕", enforce_cooldown=False) is None
    cur = await conn.execute("SELECT nickname FROM users WHERE id=1")
    assert (await cur.fetchone())["nickname"] == "핫딜왕"

    assert await set_nickname(conn, 2, "핫딜왕") == "taken"
    assert await set_nickname(conn, 2, "a!") == "invalid"
    # Re-setting your own nickname within the cooldown window is blocked.
    assert await set_nickname(conn, 1, "새닉네임") == "cooldown"
    await conn.close()
