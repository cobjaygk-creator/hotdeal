import aiosqlite
import pytest

from app.db import SCHEMA
from app.engine import auth
from app.engine.comments import list_user_comments


async def _db(tmp_path):
    conn = await aiosqlite.connect(tmp_path / "t.db")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn


async def _mk_user(conn, name, is_admin=0, username=None):
    cur = await conn.execute(
        "INSERT INTO users(display_name, username, is_admin, created_at, last_login_at) VALUES(?,?,?,?,?)",
        (name, username, is_admin, "2026-01-01", "2026-01-01"),
    )
    await conn.commit()
    return int(cur.lastrowid)


@pytest.mark.asyncio
async def test_list_users_and_toggle_admin(tmp_path):
    conn = await _db(tmp_path)
    a = await _mk_user(conn, "관리자", is_admin=1, username="admin")
    b = await _mk_user(conn, "일반유저")

    users = await auth.list_users(conn)
    assert {u["id"] for u in users} == {a, b}

    assert not auth.is_admin_user(await auth.get_user(conn, b))
    await auth.set_user_admin(conn, b, True)
    assert auth.is_admin_user(await auth.get_user(conn, b))
    await auth.set_user_admin(conn, b, False)
    assert not auth.is_admin_user(await auth.get_user(conn, b))
    await conn.close()


@pytest.mark.asyncio
async def test_delete_account_keeps_comments_anonymous(tmp_path):
    conn = await _db(tmp_path)
    uid = await _mk_user(conn, "탈퇴예정")
    await conn.execute(
        "INSERT INTO deals(product_key, product_name, first_seen_at, last_seen_at) VALUES('k','상품','2026-01-01','2026-01-01')"
    )
    await conn.execute("INSERT INTO user_bookmarks(user_id, deal_id, created_at) VALUES(?,1,'2026-01-01')", (uid,))
    await conn.execute("INSERT INTO user_keywords(user_id, keyword, min_grade, created_at) VALUES(?,'x','핫딜','2026-01-01')", (uid,))
    await conn.execute(
        "INSERT INTO deal_comments(deal_id, user_id, nickname, client_key, body, created_at) VALUES(1,?,?,?,?,?)",
        (uid, "나", "ck", "댓글 내용", "2026-01-01"),
    )
    await conn.commit()

    assert len(await list_user_comments(conn, uid)) == 1

    await auth.delete_account(conn, uid)

    assert await auth.get_user(conn, uid) is None
    cur = await conn.execute("SELECT COUNT(*) AS c FROM user_bookmarks WHERE user_id=?", (uid,))
    assert (await cur.fetchone())["c"] == 0
    cur = await conn.execute("SELECT COUNT(*) AS c FROM user_keywords WHERE user_id=?", (uid,))
    assert (await cur.fetchone())["c"] == 0
    cur = await conn.execute("SELECT user_id, body FROM deal_comments WHERE deal_id=1")
    row = await cur.fetchone()
    assert row["user_id"] is None and row["body"] == "댓글 내용"
    await conn.close()
