import asyncio

import pytest

import app.sources.dealbada as source_mod

from app.http_client import FetchResult
from app.sources.dealbada import DealbadaSource


HTML = """
<table><tr><td class='td_subject'>
<a href='https://www.dealbada.com/bbs/board.php?bo_table=deal_domestic&amp;wr_id=9'>국내 상품 9,900원</a>
</td><td class='td_date'>09:00</td></tr></table>
"""


class Client:
    def __init__(self):
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("proxy")))
        if "deal_oversea" in url and not kwargs.get("proxy"):
            raise RuntimeError("522")
        board = "deal_oversea" if "deal_oversea" in url else "deal_domestic"
        html = HTML.replace("deal_domestic", board)
        return FetchResult(url, 200, html, html.encode())


@pytest.mark.asyncio
async def test_dealbada_recovers_failed_board_through_proxy(monkeypatch):
    monkeypatch.setattr("app.sources.dealbada.PPOMPPU_PROXY_URL", "http://proxy.test:1")
    client = Client()
    posts = await DealbadaSource().fetch_latest(client)
    assert len(posts) == 2
    assert client.calls == [
        ("https://www.dealbada.com/bbs/board.php?bo_table=deal_domestic", None),
        ("https://www.dealbada.com/bbs/board.php?bo_table=deal_oversea", None),
        ("https://www.dealbada.com/bbs/board.php?bo_table=deal_oversea", "http://proxy.test:1"),
    ]


@pytest.mark.asyncio
async def test_dealbada_keeps_other_board_when_no_proxy(monkeypatch):
    monkeypatch.setattr("app.sources.dealbada.PPOMPPU_PROXY_URL", "")
    client = Client()
    posts = await DealbadaSource().fetch_latest(client)
    assert len(posts) == 1
    assert posts[0].source_post_id == "deal_domestic:9"


@pytest.mark.asyncio
async def test_stalled_direct_requests_reach_proxy_within_source_deadline(monkeypatch):
    monkeypatch.setattr(source_mod, "PPOMPPU_PROXY_URL", "http://proxy.test:1")
    monkeypatch.setattr(source_mod, "DIRECT_BUDGET_SECONDS", .02)
    monkeypatch.setattr(source_mod, "PROXY_BUDGET_SECONDS", .1)
    calls = []
    cancelled = []

    class StalledClient(Client):
        async def get(self, url, **kwargs):
            calls.append(kwargs)
            if not kwargs["proxy"]:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(url)
            return await super().get(url, **kwargs)

    async with asyncio.timeout(1):
        posts = await DealbadaSource().fetch_latest(StalledClient())
    assert len(posts) == 2
    assert len(cancelled) == 2
    assert [bool(c["proxy"]) for c in calls] == [False, True, False, True]
    assert all(c["max_retries"] == 1 and not c["curl_fallback"] for c in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_board", ["deal_domestic", "deal_oversea"])
async def test_board_timeout_preserves_other_board_in_both_orders(monkeypatch, failed_board):
    monkeypatch.setattr(source_mod, "PPOMPPU_PROXY_URL", "http://proxy.test:1")
    monkeypatch.setattr(source_mod, "DIRECT_BUDGET_SECONDS", .02)
    monkeypatch.setattr(source_mod, "PROXY_BUDGET_SECONDS", .02)

    class PartialClient(Client):
        async def get(self, url, **kwargs):
            if failed_board in url:
                await asyncio.Event().wait()
            return await super().get(url, **kwargs)

    posts = await DealbadaSource().fetch_latest(PartialClient())
    assert len(posts) == 1
    assert not posts[0].source_post_id.startswith(failed_board)


@pytest.mark.asyncio
async def test_both_boards_failed_enters_source_cooldown(monkeypatch):
    from app.collection_guard import fetch_sources

    monkeypatch.setattr(source_mod, "PPOMPPU_PROXY_URL", "http://proxy.test:1")

    class FailedClient:
        async def get(self, *args, **kwargs):
            raise TimeoutError

    failures = {}
    results = await fetch_sources([DealbadaSource()], FailedClient(), failures)
    assert "dealbada" in failures
    with pytest.raises(RuntimeError, match="all dealbada boards failed") as exc:
        await results[0].fetch_latest(None)
    assert "deal_domestic" in str(exc.value) and "deal_oversea" in str(exc.value)
    assert "proxy=TimeoutError" in str(exc.value)


@pytest.mark.asyncio
async def test_not_modified_is_success_not_failure(monkeypatch):
    monkeypatch.setattr(source_mod, "PPOMPPU_PROXY_URL", "")

    class UnchangedClient:
        async def get(self, url, **kwargs):
            return FetchResult(url, 304, "", b"", not_modified=True)

    assert await DealbadaSource().fetch_latest(UnchangedClient()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(403, "Forbidden"), (200, "Just a moment")])
async def test_blocked_direct_response_tries_proxy(monkeypatch, status, body):
    monkeypatch.setattr(source_mod, "PPOMPPU_PROXY_URL", "http://proxy.test:1")

    class BlockedClient(Client):
        async def get(self, url, **kwargs):
            if not kwargs["proxy"]:
                return FetchResult(url, status, body, body.encode())
            return await super().get(url, **kwargs)

    assert len(await DealbadaSource().fetch_latest(BlockedClient())) == 2


@pytest.mark.asyncio
async def test_shutdown_cancellation_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(source_mod, "PPOMPPU_PROXY_URL", "http://proxy.test:1")

    class CancelledClient:
        async def get(self, *args, **kwargs):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await DealbadaSource().fetch_latest(CancelledClient())
