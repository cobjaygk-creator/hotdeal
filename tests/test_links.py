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


def test_prefer_coupang_pdp_over_partner_gate():
    html = """
    <a href="https://unsafelink.com/https://www.coupang.com/vp/products/8174473713?itemId=19977722612&amp;vendorItemId=88377301608">링크</a>
    <script>{"el":{"https://link.coupang.com/a/gK5O00F3GC":"x"}}</script>
    """
    assert extract_mall_url(html) == (
        "https://www.coupang.com/vp/products/8174473713?itemId=19977722612&vendorItemId=88377301608"
    )


def test_reject_naver_searchad_junk():
    junk = "http://saedu.naver.com/adbiz/searchad/intro.nhn"
    assert not is_mall_url(junk)
    assert extract_mall_url(f'<a href="{junk}">ads</a> https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=123') == (
        "https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=123"
    )


def test_coupa_ng_short_link():
    assert is_mall_url("https://coupa.ng/b2abcde")
    assert extract_mall_url("https://coupa.ng/b2abcde") == "https://coupa.ng/b2abcde"


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


def test_quasarzone_gotolink_base64():
    from app.parse.links import extract_goto_shop, extract_shop_url

    html = (
        "<a href=\"javascript:goToLink("
        "'aHR0cHM6Ly9pdGVtLmdtYXJrZXQuY28ua3IvSXRlbT9nb29kc2NvZGU9NDIxMjc1ODkzMA=='"
        ");\">buy</a>"
    )
    assert extract_goto_shop(html) == "https://item.gmarket.co.kr/Item?goodscode=4212758930"
    assert extract_shop_url(html) == "https://item.gmarket.co.kr/Item?goodscode=4212758930"


def test_prefer_ably_over_nhnace_ad():
    from app.parse.links import extract_shop_url, is_junk_mall_url, prefers_mall

    ad = (
        "https://cdn.nhnace.com/libs/aceadlib.html?pub_code=1281125299"
        "&area_code=1743151083&pag=fmkorea.com"
    )
    good = "https://mobile.a-bly.com/goods/63730285"
    html = f'<a href="{ad}">ad</a><a href="{good}">buy</a>'
    assert is_junk_mall_url(ad)
    assert is_mall_url(good)
    assert extract_shop_url(html) == good
    assert prefers_mall(good, ad)


def test_prefer_oliveyoung_over_dajooda_affiliate():
    from app.parse.links import extract_shop_url, is_junk_mall_url, prefers_mall

    html = """
    <a href="https://dajooda.com/s/MbS7q1e">ads</a>
    <a href="https://oy.run/vo6NAPxoJR5UJt">buy</a>
    <a href="https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000217595">pdp</a>
    """
    assert is_junk_mall_url("https://dajooda.com/s/MbS7q1e")
    assert extract_shop_url(html) == (
        "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000217595"
    )
    assert prefers_mall(
        "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000217595",
        "https://dajooda.com/s/MbS7q1e",
    )


def test_reject_dealbada_shortlink_api_and_page_assets():
    from app.parse.links import extract_shop_url, is_junk_mall_url

    assert is_junk_mall_url("http://dbada.kr/public/func.php?fn=makeShortLink")
    assert is_junk_mall_url("https://www.dealbada.com/bbs/func.php?fn=makeShortLink")
    # A dealbada post page: the only shop-ish looking URLs are the short-link
    # API endpoint and CDN script/doc links — none is a real mall.
    html = """
    <script>function getShortUrl(cb){ $.post('http://dbada.kr/public/func.php?fn=makeShortLink', {}); }</script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/clipboard.js/1.7.1/clipboard.min.js"></script>
    <!-- via https://css-tricks.com/snippets/jquery/draggable-without-jquery-ui/#article-header-id-1 -->
    """
    assert extract_shop_url(html) is None


def test_reject_mall_cdn_static_assets():
    from app.parse.links import extract_shop_url, is_mall_url

    js = (
        "https://cf-static.oliveyoung.co.kr/lavender/2026082601/_next/static/"
        "chunks/164f4fb6-e503072531906ba7.js"
    )
    pdp = "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000255150"
    assert not is_mall_url(js)
    assert is_mall_url(pdp)
    html = f'<script src="{js}"></script><link rel="canonical" href="{pdp}">'
    assert extract_shop_url(pdp, html) == pdp


def test_oy_run_is_mall_shortener():
    assert is_mall_url("https://oy.run/vo6NAPxoJR5UJt")
    assert extract_mall_url(
        "본문 https://oy.run/vo6NAPxoJR5UJt https://dajooda.com/s/MbS7q1e"
    ) == "https://oy.run/vo6NAPxoJR5UJt"


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
