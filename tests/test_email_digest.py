import aiosqlite
import pytest

from app.db import SCHEMA
from app.engine import email_digest as ed


async def _db(tmp_path):
    conn = await aiosqlite.connect(tmp_path / "t.db")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn


def test_build_digest_escapes_and_lists():
    items = [
        {"id": 1, "product_name": "<b>삼겹살</b> 1kg", "seller": "몰A", "price": 9900},
        {"id": 2, "product_name": "에어팟", "seller": None, "price": None},
    ]
    subject, body_html, text = ed.build_digest(items)
    assert "2건" in subject
    assert "&lt;b&gt;삼겹살&lt;/b&gt;" in body_html  # escaped, not raw tags
    assert "<b>삼겹살</b>" not in body_html
    assert "/deal/1" in text and "/deal/2" in text
    assert "가격 미확인" in text  # None price handled


@pytest.mark.asyncio
async def test_recipients_and_top_deals(tmp_path):
    conn = await _db(tmp_path)
    await conn.execute(
        "INSERT INTO users(display_name, email, digest_opt_in, created_at, last_login_at) "
        "VALUES('a','a@x.com',1,'x','x')"
    )
    await conn.execute(
        "INSERT INTO users(display_name, email, digest_opt_in, created_at, last_login_at) "
        "VALUES('b','b@x.com',0,'x','x')"  # not opted in
    )
    await conn.execute(
        "INSERT INTO users(display_name, email, digest_opt_in, created_at, last_login_at) "
        "VALUES('c',NULL,1,'x','x')"  # opted in but no email
    )
    await conn.execute(
        "INSERT INTO deals(product_key, product_name, grade, score, first_seen_at, last_seen_at) "
        "VALUES('k1','초특가상품','🔥🔥🔥 초특가',9, datetime('now'), datetime('now'))"
    )
    await conn.execute(
        "INSERT INTO deals(product_key, product_name, grade, score, first_seen_at, last_seen_at) "
        "VALUES('k2','일반상품','일반',1, datetime('now'), datetime('now'))"
    )
    await conn.commit()

    assert await ed.digest_recipients(conn) == ["a@x.com"]
    top = await ed._top_deals_today(conn)
    assert [d["product_name"] for d in top] == ["초특가상품"]
    await conn.close()


@pytest.mark.asyncio
async def test_run_digest_guards_and_send(tmp_path, monkeypatch):
    conn = await _db(tmp_path)
    await conn.execute(
        "INSERT INTO users(display_name, email, digest_opt_in, created_at, last_login_at) "
        "VALUES('a','a@x.com',1,'x','x')"
    )
    await conn.execute(
        "INSERT INTO deals(product_key, product_name, grade, score, first_seen_at, last_seen_at) "
        "VALUES('k1','초특가','🔥🔥 특가',5, datetime('now'), datetime('now'))"
    )
    await conn.commit()

    monkeypatch.setattr(ed, "EMAIL_DIGEST_ENABLED", True)
    sent_to = []

    async def fake_send(addr, subject, body_html, text):
        sent_to.append(addr)
        return True

    monkeypatch.setattr(ed, "send_email", fake_send)

    r1 = await ed.run_digest(conn)
    assert r1["sent"] == 1 and sent_to == ["a@x.com"]

    # second call same day -> skipped
    r2 = await ed.run_digest(conn)
    assert r2 == {"skipped": "already sent today"}

    # force overrides the day guard
    r3 = await ed.run_digest(conn, force=True)
    assert r3["sent"] == 1
    await conn.close()


@pytest.mark.asyncio
async def test_run_digest_dormant_without_config(tmp_path, monkeypatch):
    conn = await _db(tmp_path)
    monkeypatch.setattr(ed, "EMAIL_DIGEST_ENABLED", False)
    assert await ed.run_digest(conn) == {"skipped": "not configured"}
    await conn.close()
