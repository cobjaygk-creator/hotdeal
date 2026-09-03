import pytest

from app.engine.naver_seed import _parse_item, _same_mall, get_market_compare


def test_parse_and_same_mall():
    tokens = {"크리넥스", "행주", "45매"}
    item = {
        "title": "<b>크리넥스</b> 빨아쓰는 위생행주 45매",
        "lprice": "16170",
        "mallName": "네이버",
        "link": "https://shop.example/1",
        "productId": "123",
    }
    parsed = _parse_item(item, tokens, min_sim=0.2)
    assert parsed is not None
    assert parsed["price"] == 16170
    assert parsed["url"].startswith("https://")
    assert _same_mall("네이버", "네이버쇼핑")
    assert not _same_mall("쿠팡", "지마켓")


@pytest.mark.asyncio
async def test_get_market_compare_disabled(monkeypatch, tmp_path):
    import aiosqlite

    from app.db import SCHEMA

    monkeypatch.setattr("app.engine.naver_seed.NAVER_SEED_ENABLED", False)
    conn = await aiosqlite.connect(tmp_path / "m.db")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    out = await get_market_compare(
        conn,
        product_key="a|b",
        product_name="테스트 상품",
        deal_price=10000,
        deal_seller="쿠팡",
    )
    assert out["enabled"] is False
    assert out["items"] == []
    await conn.close()


@pytest.mark.asyncio
async def test_get_market_compare_groups_malls(monkeypatch, tmp_path):
    import aiosqlite

    from app.db import SCHEMA

    monkeypatch.setattr("app.engine.naver_seed.NAVER_SEED_ENABLED", True)
    monkeypatch.setattr("app.engine.naver_seed.COMPARE_SIMILARITY", 0.1)

    async def fake_search(query, display=12):
        return [
            {
                "title": "테스트 상품 세트",
                "lprice": "12000",
                "mallName": "G마켓",
                "link": "https://g.example/1",
                "productId": "1",
            },
            {
                "title": "테스트 상품 세트 특가",
                "lprice": "15000",
                "mallName": "G마켓",
                "link": "https://g.example/2",
                "productId": "2",
            },
            {
                "title": "테스트 상품 세트",
                "lprice": "13000",
                "mallName": "11번가",
                "link": "https://11.example/1",
                "productId": "3",
            },
        ]

    monkeypatch.setattr("app.engine.naver_seed._search", fake_search)
    conn = await aiosqlite.connect(tmp_path / "m2.db")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    out = await get_market_compare(
        conn,
        product_key="테스트|상품",
        product_name="테스트 상품 세트",
        deal_price=11000,
        deal_seller="쿠팡",
        deal_url="https://coupang.example/x",
    )
    assert out["enabled"] is True
    malls = [x["mall"] for x in out["items"]]
    assert malls.count("G마켓") == 1
    assert "11번가" in malls
    deal = next(x for x in out["items"] if x["is_deal"])
    assert deal["price"] == 11000
    assert out["items"][0]["price"] <= out["items"][-1]["price"]
    await conn.close()
