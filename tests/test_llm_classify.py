import pytest

from app.engine import llm_classify
from app.engine.llm_classify import _parse_response, reclassify_pending


def test_parse_response_plain_json():
    assert _parse_response('{"1": "식품", "2": "의류"}') == {1: "식품", 2: "의류"}


def test_parse_response_fenced_and_prose():
    text = "분류 결과입니다:\n```json\n{\"10\": \"PC\", \"11\": \"가전\"}\n```\n끝"
    assert _parse_response(text) == {10: "PC", 11: "가전"}


def test_parse_response_drops_invalid_category_and_keys():
    text = '{"1": "식품", "2": "음식", "x": "PC", "3": "게임"}'
    assert _parse_response(text) == {1: "식품", 3: "게임"}


def test_parse_response_garbage():
    assert _parse_response("no json here") == {}
    assert _parse_response("[1, 2, 3]") == {}


@pytest.mark.asyncio
async def test_classify_batch_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_ENABLED", False)
    assert await llm_classify.classify_batch([{"id": 1, "title": "새우깡"}]) == {}


class _FakeCur:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.updates = []
        self.meta = []

    async def execute(self, sql, params=()):
        if "FROM deals d" in sql and "SELECT d.id" in sql:
            return _FakeCur(self._rows)
        self.updates.append((" ".join(sql.split()), params))
        return _FakeCur([])

    async def commit(self):
        return None


def _rows():
    return [
        {"id": 1, "product_name": "종근당 오메가3 6개월분", "seller": None,
         "category": "기타", "raw_json": None},
        {"id": 2, "product_name": "나이키 에어포스1 운동화", "seller": None,
         "category": "식품", "raw_json": None},  # wrong -> should change
        {"id": 3, "product_name": "삼다수 2L 12병", "seller": None,
         "category": "식품", "raw_json": None},  # already right
    ]


@pytest.mark.asyncio
async def test_reclassify_updates_wrong_and_marks_source(monkeypatch):
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_BATCH", 25)

    async def fake_batch(items):
        assert {it["id"] for it in items} == {1, 2, 3}
        return {1: "식품", 2: "의류", 3: "식품"}

    monkeypatch.setattr(llm_classify, "classify_batch", fake_batch)

    async def fake_set_meta(conn, key, value):
        conn.meta.append((key, value))

    monkeypatch.setattr(llm_classify, "set_meta", fake_set_meta)

    conn = _FakeConn(_rows())
    out = await reclassify_pending(conn, limit=100)

    # id 1 (기타 -> 식품) and id 2 (식품 -> 의류) both flip; id 3 already 식품.
    assert out["changed"] == 2
    assert out["checked"] == 3
    # (cat, src, id) per "SET category = ?, category_source = ? WHERE id = ?"
    cat_by_id = {
        p[2]: p[0] for sql, p in conn.updates if "UPDATE deals SET category = ?" in sql
    }
    assert cat_by_id == {1: "식품", 2: "의류"}
    # id 3 (no category change) still gets pinned so it is not re-checked
    src_only = [
        p for sql, p in conn.updates
        if "SET category_source = ?" in sql and "SET category = ?" not in sql
    ]
    assert [p[1] for p in src_only] == [3]
    assert src_only[0][0] == llm_classify._SRC  # pinned to the model tag
    assert llm_classify._SRC.startswith("llm:")


@pytest.mark.asyncio
async def test_reclassify_leaves_rows_unmarked_on_api_failure(monkeypatch):
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_BATCH", 25)

    async def dead_batch(items):
        return {}  # API error path

    monkeypatch.setattr(llm_classify, "classify_batch", dead_batch)
    monkeypatch.setattr(llm_classify, "set_meta", lambda *a, **k: _noop())

    conn = _FakeConn(_rows())
    out = await reclassify_pending(conn, limit=100)
    assert out["changed"] == 0
    assert not any("UPDATE deals" in sql for sql, _ in conn.updates)


async def _noop():
    return None


@pytest.mark.asyncio
async def test_reclassify_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_ENABLED", False)
    out = await reclassify_pending(_FakeConn(_rows()))
    assert out["skipped"] is True


@pytest.mark.asyncio
async def test_reclassify_reset_reopens_llm_rows(monkeypatch):
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_BATCH", 25)
    monkeypatch.setattr(llm_classify, "classify_batch", lambda items: _empty())

    async def fake_set_meta(conn, key, value):
        conn.meta.append((key, value))

    monkeypatch.setattr(llm_classify, "set_meta", fake_set_meta)

    conn = _FakeConn([])
    await reclassify_pending(conn, reset="기타")
    assert any(
        "UPDATE deals SET category_source = NULL" in sql and "category = '기타'" in sql
        for sql, _ in conn.updates
    )
    conn2 = _FakeConn([])
    await reclassify_pending(conn2, reset="all")
    assert any(
        sql.strip()
        == "UPDATE deals SET category_source = NULL WHERE category_source LIKE 'llm%'"
        for sql, _ in conn2.updates
    )


async def _empty():
    return {}


@pytest.mark.asyncio
async def test_reclassify_maps_positional_response(monkeypatch):
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(llm_classify, "LLM_CLASSIFY_BATCH", 25)

    async def positional_batch(items):
        # model answered 1..N by position, ignoring the real ids
        return {1: "식품", 2: "의류", 3: "식품"}

    monkeypatch.setattr(llm_classify, "classify_batch", positional_batch)

    async def fake_set_meta(conn, key, value):
        conn.meta.append((key, value))

    monkeypatch.setattr(llm_classify, "set_meta", fake_set_meta)

    conn = _FakeConn(_rows())  # ids 1,2,3 — collides, so make them big
    for i, r in enumerate(conn._rows):
        r["id"] = 5000 + i
    out = await reclassify_pending(conn, limit=100)
    assert out["checked"] == 3
    # UPDATE ... SET category = ?, category_source = ? WHERE id = ?  -> (cat, src, id)
    cat_updates = {p[2]: p[0] for sql, p in conn.updates if "SET category = ?" in sql}
    # positional map applied: 5000 오메가3 기타->식품, 5001 에어포스1 식품->의류,
    # 5002 삼다수 stays 식품 (no category write)
    assert cat_updates == {5000: "식품", 5001: "의류"}
