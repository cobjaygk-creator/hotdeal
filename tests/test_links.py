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


def test_reject_bare_mall_homepage():
    assert not is_mall_url("https://www.coupang.com/")
    assert not is_mall_url("https://www.coupang.com")


def test_reject_truncated_gmarket_url():
    bad = "https://item.gmarket.co.kr/Item?spm=gmktpc.pdp.0.0.26d36188DIXkWJ&good…"
    assert not is_mall_url(bad)
    assert extract_mall_url(bad) is None


def test_accept_full_gmarket_goodscode():
    good = "https://item.gmarket.co.kr/Item?goodscode=4828575079"
    assert is_mall_url(good)


def test_unwrap_community_redirect():
    html = (
        '<a href="https://www.dealbada.com/bbs/link.php?'
        'url=https%3A%2F%2Fitem.gmarket.co.kr%2FItem%3Fgoodscode%3D4828575079">buy</a>'
    )
    assert extract_mall_url(html) == "https://item.gmarket.co.kr/Item?goodscode=4828575079"


def test_unwrap_gmarket_affiliate_gate():
    gate = (
        "https://link.gmarket.co.kr/gate/channel?service-code=10021003"
        "&target-url=https%3A%2F%2Fitem.gmarket.co.kr%2FItem%3FgoodsCode%3D4331858761"
    )
    assert is_mall_url(gate)
    assert extract_mall_url(gate) == "https://item.gmarket.co.kr/Item?goodsCode=4331858761"


def test_strip_trailing_korean_on_short_link():
    dirty = "https://naver.me/xiL30JlA상품링크 https://naver.me/xrzZWvl66대카드사"
    assert extract_mall_url(dirty) == "https://naver.me/xiL30JlA"


def test_unwrap_ppomppu_target_base64():
    # https://smartstore.naver.com/foo/products/1
    target = "aHR0cHM6Ly9zbWFydHN0b3JlLm5hdmVyLmNvbS9mb28vcHJvZHVjdHMvMQ=="
    href = f"https://s.ppomppu.co.kr?idno=ppomppu_1&target={target}"
    assert extract_mall_url(f'<a href="{href}">buy</a>') == (
        "https://smartstore.naver.com/foo/products/1"
    )


def test_unwrap_unsafelink_prefix():
    from app.parse.links import extract_shop_url, is_mall_url

    wrapped = (
        "https://unsafelink.com/https://seorincomputer.co.kr/"
        "shop/system_detail.html?sid=PC-1"
    )
    assert extract_shop_url(wrapped) == (
        "https://seorincomputer.co.kr/shop/system_detail.html?sid=PC-1"
    )
    assert not is_mall_url(wrapped)


def test_unwrap_community_to_brand_shop():
    from app.parse.links import extract_shop_url

    html = (
        '<a href="https://www.clien.net/service/board/jirum/1?'
        'url=https%3A%2F%2Fshop.examplebrand.co.kr%2Fproduct%2F99">buy</a>'
    )
    assert extract_shop_url(html) == "https://shop.examplebrand.co.kr/product/99"
