import pytest

from app.db import connect
from app.pipeline import collect_and_process
from app.sources import RawPost
from app.sources.registry import (
    ALL_SOURCES,
    COLLECT_FAST_SOURCES,
    COLLECT_PROXY_SOURCES,
    COLLECT_QUASARZONE_SOURCES,
    COLLECT_SLOW_SOURCES,
)


class _ListSource:
    name = "clien"

    async def fetch_latest(self, client):
        return [
            RawPost(
                source="clien",
                source_post_id="99",
                url="https://www.clien.net/service/board/jirum/99",
                title="[할인] 무선마우스 9,900원",
                body="본문에 링크 없음",
            )
        ]


@pytest.mark.asyncio
async def test_list_tick_skips_detail_fetch(tmp_path, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise AssertionError("list collect must not open detail pages")

    monkeypatch.setattr("app.sources.detail.enrich_post", boom)
    conn = await connect(tmp_path / "list-tick.db")
    try:
        summary = await collect_and_process(conn, [_ListSource()], object())
        assert summary["new_posts"] == 1
        assert summary["sources"]["clien"]["fetched"] == 1
        assert summary["errors"] == []
    finally:
        await conn.close()


def test_collect_tiers_cover_every_source():
    scheduled = set(
        COLLECT_FAST_SOURCES
        + COLLECT_PROXY_SOURCES
        + COLLECT_QUASARZONE_SOURCES
        + COLLECT_SLOW_SOURCES
    )
    scheduled.add("ppomppu")
    assert {s.name for s in ALL_SOURCES} == scheduled
    assert not (set(COLLECT_FAST_SOURCES) & set(COLLECT_PROXY_SOURCES))
    assert "coolenjoy" in COLLECT_SLOW_SOURCES
