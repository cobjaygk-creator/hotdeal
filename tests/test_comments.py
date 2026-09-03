import pytest

from app.engine.comments import (
    CommentError,
    add_comment,
    check_rate,
    comment_counts,
    delete_comment,
    normalize_body,
    normalize_nickname,
    normalize_pin,
    toggle_reaction,
)


def test_normalize_helpers():
    assert normalize_nickname("") == "익명"
    assert normalize_nickname("  nickname-too-long ") == "nickname-too"
    assert normalize_body("괜찮아요") == "괜찮아요"
    with pytest.raises(CommentError):
        normalize_body(" ")
    assert normalize_pin("12 34") == "1234"
    with pytest.raises(CommentError):
        normalize_pin("12")


def test_rate_limit_blocks_burst():
    from app.engine import comments as mod

    mod._rate_hits.clear()
    check_rate("k1", "1.1.1.1")
    with pytest.raises(CommentError):
        check_rate("k1", "1.1.1.1")
    mod._rate_hits.clear()


@pytest.mark.asyncio
async def test_comment_lifecycle_and_soldout(tmp_path, monkeypatch):
    import aiosqlite

    from app.db import SCHEMA, utcnow_iso

    monkeypatch.setattr("app.engine.comments.SOLDOUT_REPORT_THRESHOLD", 2)
    db_path = tmp_path / "c.db"
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.execute(
        """
        INSERT INTO deals(product_key, product_name, first_seen_at, last_seen_at, status)
        VALUES('k','테스트',?,?, 'active')
        """,
        (utcnow_iso(), utcnow_iso()),
    )
    await conn.commit()

    from app.engine import comments as mod

    mod._rate_hits.clear()
    item = await add_comment(
        conn,
        deal_id=1,
        nickname="테스터",
        pin="1234",
        body="가격 괜찮네요",
        parent_id=None,
        client_key="aaa",
        user=None,
        ip="2.2.2.2",
    )
    assert item["nickname"] == "테스터"
    assert item["mine"] is True
    counts = await comment_counts(conn, [1])
    assert counts[1] == 1

    with pytest.raises(CommentError):
        await add_comment(
            conn,
            deal_id=1,
            nickname="테스터",
            pin="1234",
            body="가격 괜찮네요",
            parent_id=None,
            client_key="aaa",
            user=None,
            ip="2.2.2.2",
        )

    mod._rate_hits.clear()
    with pytest.raises(CommentError):
        await add_comment(
            conn,
            deal_id=1,
            nickname="스팸",
            pin="9999",
            body="https://spam.example",
            parent_id=None,
            client_key="bbb",
            user=None,
            ip="3.3.3.3",
        )

    await delete_comment(conn, item["id"], pin="1234", client_key="aaa", is_admin=False)
    counts = await comment_counts(conn, [1])
    assert counts.get(1, 0) == 0

    await toggle_reaction(conn, deal_id=1, client_key="c1", kind="soldout")
    snap = await toggle_reaction(conn, deal_id=1, client_key="c2", kind="soldout")
    assert snap["expired"] is True
    cur = await conn.execute("SELECT status FROM deals WHERE id=1")
    assert (await cur.fetchone())["status"] == "expired"
    await conn.close()
