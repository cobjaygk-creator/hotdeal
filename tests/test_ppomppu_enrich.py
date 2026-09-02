import json

import pytest

from app.engine.ppomppu_enrich import enrich_missing_ppomppu_malls


@pytest.mark.asyncio
async def test_enrich_skips_without_proxy(monkeypatch):
    monkeypatch.setattr("app.engine.ppomppu_enrich.PPOMPPU_PROXY_URL", "")
    out = await enrich_missing_ppomppu_malls(None, None)
    assert out["skipped"] is True
    assert out["filled"] == 0


@pytest.mark.asyncio
async def test_enrich_updates_mall(monkeypatch):
    monkeypatch.setattr(
        "app.engine.ppomppu_enrich.PPOMPPU_PROXY_URL", "http://proxy.example:8080"
    )

    class FakeDetail:
        mall_url = "https://item.gmarket.co.kr/Item?goodscode=1"
        thumbnail_url = "https://cdn.example/a.jpg"

    async def fake_enrich(client, source, url):
        assert source == "ppomppu"
        return FakeDetail()

    monkeypatch.setattr("app.engine.ppomppu_enrich.enrich_post", fake_enrich)

    class FakeCur:
        def __init__(self, rows):
            self._rows = rows

        async def fetchall(self):
            return self._rows

    class FakeConn:
        def __init__(self):
            self.updates = []
            self.meta = None

        async def execute(self, sql, params=()):
            if "SELECT d.id" in sql:
                return FakeCur(
                    [
                        {
                            "deal_id": 9,
                            "post_id": 3,
                            "post_url": "https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=1",
                        }
                    ]
                )
            self.updates.append((sql, params))
            return FakeCur([])

        async def commit(self):
            return None

    conn = FakeConn()

    async def fake_set_meta(c, key, value):
        conn.meta = (key, json.loads(value))

    monkeypatch.setattr("app.engine.ppomppu_enrich.set_meta", fake_set_meta)
    out = await enrich_missing_ppomppu_malls(conn, object(), limit=5)
    assert out["skipped"] is False
    assert out["filled"] == 1
    assert any("UPDATE deals" in sql for sql, _ in conn.updates)
    assert conn.meta[0] == "last_ppomppu_mall_enrich"


class _RowsConn:
    """Minimal aiosqlite-like conn that yields a fixed batch of deal rows."""

    def __init__(self, count):
        self.rows = [
            {
                "deal_id": i,
                "post_id": 100 + i,
                "post_url": f"https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no={i}",
            }
            for i in range(count)
        ]
        self.updates = []
        self.meta = None

    async def execute(self, sql, params=()):
        if "SELECT d.id" in sql:
            return _FetchAll(self.rows)
        self.updates.append((sql, params))
        return _FetchAll([])

    async def commit(self):
        return None


class _FetchAll:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


def _patch_common(monkeypatch, conn):
    monkeypatch.setattr(
        "app.engine.ppomppu_enrich.PPOMPPU_PROXY_URL", "http://proxy.example:8080"
    )

    async def fake_set_meta(c, key, value):
        conn.meta = (key, json.loads(value))

    monkeypatch.setattr("app.engine.ppomppu_enrich.set_meta", fake_set_meta)


@pytest.mark.asyncio
async def test_enrich_counts_no_link_without_stopping_batch(monkeypatch):
    conn = _RowsConn(5)
    _patch_common(monkeypatch, conn)

    from app.sources.detail import DetailEnrichment

    async def fake_enrich(client, source, url):
        # Clean fetch, but the post simply has no buy link.
        return DetailEnrichment(title="정보글", blocked=False)

    monkeypatch.setattr("app.engine.ppomppu_enrich.enrich_post", fake_enrich)

    out = await enrich_missing_ppomppu_malls(conn, object(), limit=5)
    assert out["filled"] == 0
    assert out["no_link"] == 5
    assert out["blocked"] == 0
    # Every row was attempted; a missing link must not abort the batch.
    assert out["attempted"] == 5


@pytest.mark.asyncio
async def test_enrich_stops_batch_after_consecutive_blocks(monkeypatch):
    conn = _RowsConn(12)
    _patch_common(monkeypatch, conn)

    from app.sources.detail import DetailEnrichment

    async def fake_enrich(client, source, url):
        return DetailEnrichment(blocked=True)

    monkeypatch.setattr("app.engine.ppomppu_enrich.enrich_post", fake_enrich)

    out = await enrich_missing_ppomppu_malls(conn, object(), limit=12)
    assert out["filled"] == 0
    assert out["no_link"] == 0
    # Bails out after 3 consecutive real blocks instead of burning all 12.
    assert out["blocked"] == 3
