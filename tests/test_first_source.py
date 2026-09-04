import pytest

from app.db import connect
from app.main import _attach_sources
from app.pipeline import fetch_deal_card


async def _seed(conn):
    now = "2026-09-04T00:00:00+00:00"
    await conn.execute(
        "INSERT INTO deals(id, product_key, product_name, first_seen_at, last_seen_at) "
        "VALUES(1, 'k', 'thing', ?, ?)",
        (now, now),
    )
    # clien collected first, ppomppu second
    rows = [
        (10, "clien", "c1", "2026-09-04T01:00:00+00:00"),
        (11, "ppomppu", "p1", "2026-09-04T02:00:00+00:00"),
    ]
    for pid, src, spid, cat in rows:
        await conn.execute(
            "INSERT INTO posts(id, source, source_post_id, url, title, collected_at) "
            "VALUES(?, ?, ?, ?, 't', ?)",
            (pid, src, spid, f"https://x/{spid}", cat),
        )
        await conn.execute(
            "INSERT INTO deal_posts(deal_id, post_id) VALUES(1, ?)", (pid,)
        )
    await conn.commit()


@pytest.mark.asyncio
async def test_attach_sources_first_source_is_earliest_collected(tmp_path):
    conn = await connect(tmp_path / "fs.db")
    try:
        await _seed(conn)
        deals = [{"id": 1}]
        await _attach_sources(conn, deals)
        assert deals[0]["first_source"] == "clien"
        assert set(deals[0]["sources"].split(",")) == {"clien", "ppomppu"}
        assert deals[0]["sources"].split(",")[0] == "clien"  # ordered
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fetch_deal_card_first_source(tmp_path):
    conn = await connect(tmp_path / "fs2.db")
    try:
        await _seed(conn)
        card = await fetch_deal_card(conn, 1)
        assert card["first_source"] == "clien"
    finally:
        await conn.close()
