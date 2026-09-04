import pytest

from app.http_client import FetchResult
from app.sources.html_fetch import block_reason, fetch_parsed
from app.sources import RawPost


def test_block_reason_challenge():
    result = FetchResult(
        url="https://arca.live/b/hotdeal",
        status=200,
        text="<html>Just a moment... cf-browser-verification</html>",
        content=b"",
    )
    assert block_reason(result) == "blocked:just a moment"


def test_block_reason_fmkorea_protect():
    result = FetchResult(
        url="https://www.fmkorea.com/hotdeal",
        status=200,
        text=(
            "<html><head><title>이용자보호 조치 시스템</title></head>"
            "<body>IP: 1.2.3.4 잠시 기다리면 자동으로 연결됩니다. "
            "help@fmkorea.com</body></html>"
        ),
        content=b"",
    )
    assert block_reason(result) == "blocked:이용자보호"


def test_block_reason_ignores_cf_email_widget():
    result = FetchResult(
        url="https://damoang.net/economy",
        status=200,
        text='<html><title>경제</title><a href="/cdn-cgi/l/email-protection">mail</a></html>',
        content=b"",
    )
    assert block_reason(result) is None


def _post(n: str) -> RawPost:
    return RawPost(source="arca", source_post_id=n, url=f"https://arca.live/b/hotdeal/{n}", title="t")


class _FakeClient:
    def __init__(self):
        self.calls: list[str | None] = []

    async def get(self, url, encoding=None, timeout=None, proxy=None):
        self.calls.append(proxy)
        if proxy:
            return FetchResult(url, 200, "<ok/>", b"<ok/>")
        return FetchResult(url, 200, "Just a moment", b"Just a moment")


@pytest.mark.asyncio
async def test_fetch_parsed_uses_proxy_first_for_arca(monkeypatch):
    monkeypatch.setattr("app.sources.html_fetch.PPOMPPU_PROXY_URL", "http://proxy.test:1")
    client = _FakeClient()
    posts = await fetch_parsed(
        client, "https://arca.live/b/hotdeal", lambda html: [_post("1")]
    )
    assert len(posts) == 1
    assert client.calls[0] == "http://proxy.test:1"


@pytest.mark.asyncio
async def test_fetch_parsed_uses_proxy_first_for_fmkorea(monkeypatch):
    monkeypatch.setattr("app.sources.html_fetch.PPOMPPU_PROXY_URL", "http://proxy.test:1")
    client = _FakeClient()
    posts = await fetch_parsed(
        client,
        "https://www.fmkorea.com/hotdeal",
        lambda html: [
            RawPost(
                source="fmkorea",
                source_post_id="1",
                url="https://www.fmkorea.com/1",
                title="t",
            )
        ],
    )
    assert len(posts) == 1
    assert client.calls[0] == "http://proxy.test:1"
