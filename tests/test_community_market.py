import aiosqlite
import pytest

from app.db import SCHEMA
from app.main import _norm_mall


def test_norm_mall():
    assert _norm_mall("쿠팡!") == _norm_mall("쿠팡")


@pytest.mark.asyncio
async def test_community_market_compare_groups_sellers(tmp_path, monkeypatch):
    import app.main as main

    conn = await aiosqlite.connect(tmp_path / "t.db")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.executemany(
        """
        INSERT INTO price_points(product_key, price, unit_price, seller, source, observed_at, post_id)
        VALUES (?, ?, NULL, ?, ?, ?, ?)
        """,
        [
            ("pk1", 30000, "쿠팡", "ppomppu", "2026-08-01 10:00:00", 1),
            ("pk1", 29800, "네이버", "clien", "2026-08-02 10:00:00", 2),
            ("pk1", 32000, "G마켓", "ruliweb", "2026-08-03 10:00:00", 3),
            ("pk1", 29000, "쿠팡", "ppomppu", "2026-08-04 10:00:00", 4),
            ("pk1", 50000, "쿠팡", "naver", "2026-08-05 10:00:00", 5),
        ],
    )
    await conn.commit()
    monkeypatch.setattr(main, "_db", lambda: conn)

    out = await main._community_market_compare(
        product_key="pk1",
        deal_price=23900,
        deal_seller="쿠팡",
        deal_url="https://example.com/buy",
    )
    assert out["enabled"] is True
    assert out["mode"] == "community"
    assert out["items"][0]["is_deal"] is True
    assert out["items"][0]["price"] == 23900
    other_malls = [i["mall"] for i in out["items"] if not i["is_deal"]]
    assert "네이버" in other_malls
    assert "G마켓" in other_malls
    assert "쿠팡" not in other_malls
    await conn.close()
