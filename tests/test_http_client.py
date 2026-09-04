import pytest

from app.http_client import FetchResult, PoliteClient


def test_curl_argv_includes_proxy():
    argv = PoliteClient._curl_argv(
        "https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=1",
        timeout=20,
        proxy="http://user:pass@proxy.example:8080",
    )
    assert "-x" in argv
    assert "http://user:pass@proxy.example:8080" in argv
    assert argv[-1].startswith("https://www.ppomppu.co.kr/")


def test_curl_argv_omits_proxy_when_unset():
    argv = PoliteClient._curl_argv("https://example.com/", timeout=5, proxy=None)
    assert "-x" not in argv


@pytest.mark.asyncio
async def test_get_uses_chrome_tls_when_proxy_set():
    client = PoliteClient()

    async def fake_impersonate(url, encoding, timeout, proxy, cond=None):
        assert proxy == "http://proxy.test:1"
        return FetchResult(url, 200, "<html>ok vrow hybrid</html>", b"ok")

    client._impersonate_get = fake_impersonate  # type: ignore[method-assign]
    try:
        result = await client.get("https://arca.live/b/hotdeal", proxy="http://proxy.test:1")
        assert "vrow" in result.text
    finally:
        await client.aclose()
