import pytest

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
