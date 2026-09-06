import pytest

from app.db import connect
from app.engine.ranking import rank_deals


async def _deal(conn, did, name, seen="datetime('now')"):
    await conn.execute(
        f"INSERT INTO deals(id, product_key, product_name, first_seen_at, last_seen_at) "
        f"VALUES(?, ?, ?, {seen}, {seen})",
        (did, f"k{did}", name),
    )


@pytest.mark.asyncio
async def test_rank_deals_orders_by_blended_popularity(tmp_path):
    conn = await connect(tmp_path / "r.db")
    try:
        await _deal(conn, 1, "원문 조회수만 높은 딜")
        await _deal(conn, 2, "사이트 참여가 많은 딜")
        await _deal(conn, 3, "아무 신호 없는 딜")
        # deal 1: 5000 views via one post
        await conn.execute(
            "INSERT INTO posts(id, source, source_post_id, url, title, views, votes, collected_at) "
            "VALUES(10,'ppomppu','p10','u','t',5000,0,datetime('now'))"
        )
        await conn.execute("INSERT INTO deal_posts(deal_id, post_id) VALUES(1,10)")
        # deal 2: modest views but lots of bookmarks + comments + reactions
        await conn.execute(
            "INSERT INTO posts(id, source, source_post_id, url, title, views, votes, collected_at) "
            "VALUES(20,'clien','p20','u','t',300,20,datetime('now'))"
        )
        await conn.execute("INSERT INTO deal_posts(deal_id, post_id) VALUES(2,20)")
        for i in range(150):
            await conn.execute(
                "INSERT INTO user_bookmarks(user_id, deal_id, created_at) VALUES(?,2,'x')", (i,)
            )
        for i in range(25):
            await conn.execute(
                "INSERT INTO deal_comments(deal_id, nickname, body, created_at) VALUES(2,'n','b','x')"
            )
        for i in range(30):
            await conn.execute(
                "INSERT INTO deal_reactions(deal_id, client_key, kind, created_at) VALUES(2,?,'want','x')",
                (f"ck{i}",),
            )
        await conn.commit()

        ranked = await rank_deals(conn)
        ids = [r["id"] for r in ranked]
        # deal 1's raw views are capped at 2000; deal 2's blended engagement clears it.
        assert ids == [2, 1, 3]
        assert ranked[0]["bookmark_count"] == 150
        assert ranked[0]["site_comment_count"] == 25
        assert ranked[1]["orig_views"] == 5000  # stored value kept, only capped in the score
        assert ranked[2]["popularity"] == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_rank_deals_excludes_old_and_deleted_comments(tmp_path):
    conn = await connect(tmp_path / "r2.db")
    try:
        await _deal(conn, 1, "오래된 딜", seen="datetime('now','-2 days')")
        await _deal(conn, 2, "최근 딜")
        await conn.execute(
            "INSERT INTO deal_comments(deal_id, nickname, body, created_at, deleted_at) "
            "VALUES(2,'n','b','x','2026-01-01')"  # soft-deleted -> not counted
        )
        await conn.commit()
        ranked = await rank_deals(conn, hours=12)
        assert [r["id"] for r in ranked] == [2]
        assert ranked[0]["site_comment_count"] == 0
    finally:
        await conn.close()
