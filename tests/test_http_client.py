from app.http_client import PoliteClient


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
