import pytest

from app.engine.auth import (
    authenticate_local,
    ensure_local_admin,
    hash_password,
    is_admin_user,
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
