import pytest

from app.sources.fmkorea import FmkoreaSource, LIST_URL

_LIST_HTML = """
<ul><li class="li">
  <h3 class="title"><a href="/10296228074"><span class="ellipsis-target">[스팀] 테스트 게임 (4,500원)</span></a></h3>
  <div class="hotdeal_info"><span>쇼핑몰 : <a class="strong">스팀</a></span></div>
  <span class="author">tester</span>
  <span class="regdate">2026.09.04</span>
</li></ul>
"""


@pytest.mark.asyncio
async def test_fetch_latest_falls_back_to_browser_when_gated(monkeypatch):
    async def blocked_fetch_parsed(*_a, **_k):
        raise RuntimeError(f"blocked:help@fmkorea.com ({LIST_URL})")

    called = {}

    async def fake_browser_fetch(url, **kw):
        called["url"] = url
        return _LIST_HTML

    monkeypatch.setattr("app.sources.fmkorea.fetch_parsed", blocked_fetch_parsed)
    monkeypatch.setattr("app.sources.fm_browser.fetch_html", fake_browser_fetch)

    posts = await FmkoreaSource().fetch_latest(client=object())
    assert called["url"] == LIST_URL
    assert [p.source_post_id for p in posts] == ["10296228074"]
    assert posts[0].url == "https://www.fmkorea.com/10296228074"


@pytest.mark.asyncio
async def test_fetch_latest_reraises_when_browser_unavailable(monkeypatch):
    async def blocked_fetch_parsed(*_a, **_k):
        raise RuntimeError(f"blocked:help@fmkorea.com ({LIST_URL})")

    async def no_browser(url, **kw):
        return None

    monkeypatch.setattr("app.sources.fmkorea.fetch_parsed", blocked_fetch_parsed)
    monkeypatch.setattr("app.sources.fm_browser.fetch_html", no_browser)

    with pytest.raises(RuntimeError, match="blocked:"):
        await FmkoreaSource().fetch_latest(client=object())


@pytest.mark.asyncio
async def test_fetch_latest_does_not_touch_browser_on_other_errors(monkeypatch):
    async def other_error(*_a, **_k):
        raise RuntimeError("ReadTimeout: something")

    def explode(*_a, **_k):  # pragma: no cover - must not run
        raise AssertionError("browser should not be used")

    monkeypatch.setattr("app.sources.fmkorea.fetch_parsed", other_error)
    monkeypatch.setattr("app.sources.fm_browser.fetch_html", explode)

    with pytest.raises(RuntimeError, match="ReadTimeout"):
        await FmkoreaSource().fetch_latest(client=object())
