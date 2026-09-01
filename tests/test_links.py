from app.parse.links import extract_mall_url, is_mall_url


def test_extract_mall_from_href():
    html = '<a href="https://smartstore.naver.com/foo/products/1">buy</a>'
    assert extract_mall_url(html) == "https://smartstore.naver.com/foo/products/1"


def test_reject_community():
    assert not is_mall_url("https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=1")
    assert extract_mall_url("https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=1") is None


def test_coupang_ok():
    assert is_mall_url("https://www.coupang.com/vp/products/123")
    assert extract_mall_url("링크 https://link.coupang.com/a/AbC") == "https://link.coupang.com/a/AbC"
