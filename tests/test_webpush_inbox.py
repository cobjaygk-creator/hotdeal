import aiosqlite
import pytest

from app.db import SCHEMA
from app.engine import alerts, auth


async def _db(tmp_path):
    conn = await aiosqlite.connect(tmp_path / "t.db")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn


@pytest.mark.asyncio
async def test_empty_channel_still_creates_subs_for_inbox(tmp_path):
    conn = await _db(tmp_path)
    cur = await conn.execute(
        "INSERT INTO users(display_name, created_at, last_login_at) VALUES('u','x','x')"
    )
    uid = int(cur.lastrowid)
    await conn.execute(
        "INSERT INTO user_keywords(user_id, keyword, min_grade, created_at) VALUES(?,?,?,?)",
        (uid, "삼겹살", "핫딜", "x"),
    )
    await conn.commit()

    # no notify channel set at all
    await auth.sync_user_alert_subs(conn, {"id": uid})
    cur = await conn.execute("SELECT keyword, channel FROM alert_subs WHERE user_id=?", (uid,))
    rows = [dict(r) for r in await cur.fetchall()]
    assert rows == [{"keyword": "삼겹살", "channel": ""}]
    await conn.close()


@pytest.mark.asyncio
async def test_dispatch_records_inbox_without_channel(tmp_path):
    conn = await _db(tmp_path)
    cur = await conn.execute(
        "INSERT INTO users(display_name, created_at, last_login_at) VALUES('u','x','x')"
    )
    uid = int(cur.lastrowid)
    await conn.execute(
        "INSERT INTO alert_subs(keyword, min_grade, channel, target, enabled, origin, created_at, user_id) "
        "VALUES('삼겹살','핫딜','','',1,'user','x',?)",
        (uid,),
    )
    await conn.execute(
        "INSERT INTO deals(id, product_key, product_name, first_seen_at, last_seen_at) "
        "VALUES(1,'k','1등급 삼겹살 1kg','x','x')"
    )
    await conn.commit()

    deal = {"id": 1, "product_name": "1등급 삼겹살 1kg", "grade": "🔥 핫딜", "seller": ""}
    summary = await alerts.dispatch_alerts(conn, None, [deal])
    assert summary["sent"] == 1 and summary["errors"] == 0

    cur = await conn.execute("SELECT sub_id, deal_id, read_at FROM alert_sent")
    row = await cur.fetchone()
    assert row["deal_id"] == 1 and row["read_at"] is None
    await conn.close()


@pytest.mark.asyncio
async def test_deliver_webpush_fans_out_and_prunes_expired(tmp_path, monkeypatch):
    conn = await _db(tmp_path)
    cur = await conn.execute(
        "INSERT INTO users(display_name, created_at, last_login_at) VALUES('u','x','x')"
    )
    uid = int(cur.lastrowid)
    for i, ep in enumerate(["https://push/ok", "https://push/gone"]):
        await conn.execute(
            "INSERT INTO push_subscriptions(user_id, endpoint, p256dh, auth, created_at) VALUES(?,?,?,?,?)",
            (uid, ep, "p", "a", "x"),
        )
    await conn.commit()

    calls = []

    async def fake_send(info, payload):
        calls.append(info["endpoint"])
        return 201 if info["endpoint"].endswith("ok") else 410

    monkeypatch.setattr("app.engine.push.send_web_push", fake_send)

    sub = {"channel": "webpush", "keyword": "x", "user_id": uid, "target": ""}
    deal = {"id": 5, "product_name": "상품", "seller": "", "price": 1000}
    await alerts._deliver(conn, None, sub, deal)

    assert set(calls) == {"https://push/ok", "https://push/gone"}
    cur = await conn.execute("SELECT endpoint FROM push_subscriptions")
    left = [r["endpoint"] for r in await cur.fetchall()]
    assert left == ["https://push/ok"]
    await conn.close()
