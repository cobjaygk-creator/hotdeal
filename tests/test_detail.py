from app.sources.detail import enrich_from_list_body, parse_detail
from app.sources.quasarzone import parse_list


def test_parse_detail_prefers_board_link_over_body_coupon():
    from app.sources.detail import parse_detail

    target_goods = "aHR0cHM6Ly9zdG9yZS5vaG91LnNlL2dvb2RzLzQxOTM5NTk="
    target_coupon = "aHR0cHM6Ly9zdG9yZS5vaG91LnNlL3RvZGF5X2RlYWxzP2FjdGl2ZUluZGV4PTI="
    html = f"""
    <html><head><meta property="og:title" content="[오늘의집] 빈츠 세트 - 뽐뿌"></head>
    <body>
      <table>
        <tr><th>관련링크</th><td>
          <a href="https://s.ppomppu.co.kr?idno=ppomppu_1&target={target_goods}">buy</a>
        </td></tr>
      </table>
      <div class="board-contents">
        <p>쿠폰 받으세요</p>
        <a href="https://s.ppomppu.co.kr?idno=x&target={target_coupon}">coupon</a>
        <a href="https://store.ohou.se/today_deals?activeIndex=2">today</a>
      </div>
    </body></html>
    """
    detail = parse_detail(html, "https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=1")
    assert detail.mall_url == "https://store.ohou.se/goods/4193959"


def test_weak_today_deals_loses_to_goods():
    from app.parse.links import is_weak_mall_url, prefers_mall

    weak = "https://store.ohou.se/today_deals?activeIndex=2"
    goods = "https://store.ohou.se/goods/4193959"
    assert is_weak_mall_url(weak)
    assert not is_weak_mall_url(goods)
    assert prefers_mall(goods, weak)


def test_parse_detail_quasarzone_gotolink():
    from app.sources.detail import parse_detail

    html = """
    <html><head><meta property="og:title" content="모니터 - 퀘이사존"></head>
    <body><table><tr><th>구매링크</th><td>
    <a href="javascript:goToLink('aHR0cHM6Ly9pdGVtLmdtYXJrZXQuY28ua3IvSXRlbT9nb29kc2NvZGU9NDIxMjc1ODkzMA==');">
    https://item.gmarket.co.kr/Item?goodscode=4212758930</a>
    </td></tr></table></body></html>
    """
    detail = parse_detail(html, "https://quasarzone.com/bbs/qb_saleinfo/views/1")
    assert detail.mall_url == "https://item.gmarket.co.kr/Item?goodscode=4212758930"


def test_parse_detail_arca_prefers_coupang_pdp():
    html = """
    <html><head><meta property="og:title" content="콜라 - 아카라이브"></head>
    <body>
      <article>
        <a href="https://unsafelink.com/https://www.coupang.com/vp/products/8174473713?itemId=1&amp;vendorItemId=2">링크</a>
      </article>
      <script>window.__APP={"el":{"https://link.coupang.com/a/gK5O00F3GC":"encoded"}}</script>
    </body></html>
    """
    detail = parse_detail(html, "https://arca.live/b/hotdeal/181957622")
    assert detail.mall_url == (
        "https://www.coupang.com/vp/products/8174473713?itemId=1&vendorItemId=2"
    )


def test_parse_detail_og_and_mall():
    html = """
    <html><head>
      <meta property="og:title" content="[쿠팡] 테스트 상품 (12,000원/무료)">
      <meta property="og:image" content="https://cdn.example.com/a.jpg">
    </head><body>
      <div class="board-contents">
        <a href="https://www.coupang.com/vp/products/99">구매</a>
        <img src="https://cdn.example.com/b.jpg">
        <p>세탁할 때 보조로 쓰면 됩니다</p>
        <script>alert(1)</script>
        <img src="javascript:alert(1)">
      </div>
    </body></html>
    """
    detail = parse_detail(html, "https://example.com/post/1")
    assert detail.title and "테스트 상품" in detail.title
    assert detail.thumbnail_url == "https://cdn.example.com/a.jpg"
    assert detail.mall_url == "https://www.coupang.com/vp/products/99"
    assert detail.body_html
    assert "세탁할 때" in detail.body_html
    assert "cdn.example.com/b.jpg" in detail.body_html
    assert "<script" not in detail.body_html.lower()
    assert "javascript:" not in detail.body_html.lower()


def test_sanitize_strips_xss():
    from app.parse.sanitize_html import sanitize_body_html

    dirty = (
        '<p onclick="alert(1)">안녕</p>'
        '<a href="javascript:alert(1)">x</a>'
        '<img src="https://cdn.example.com/ok.jpg" onerror="alert(1)">'
        '<img data-src="/rel.jpg">'
    )
    clean = sanitize_body_html(dirty, base_url="https://board.example.com/view/1")
    assert clean
    assert "onclick" not in clean
    assert "javascript:" not in clean
    assert "onerror" not in clean
    assert 'src="https://cdn.example.com/ok.jpg"' in clean
    assert 'src="https://board.example.com/rel.jpg"' in clean
    assert 'referrerpolicy="no-referrer"' in clean



def test_parse_detail_ppomppu_shortener():
    # https://item.gmarket.co.kr/Item?goodscode=2713640571
    target = (
        "aHR0cHM6Ly9pdGVtLmdtYXJrZXQuY28ua3IvSXRlbT9nb29kc2NvZGU9MjcxMzY0MDU3MQ=="
    )
    html = f"""
    <html><body>
      <div class="board-contents">
        <a href="https://s.ppomppu.co.kr?idno=ppomppu_1&target={target}">buy</a>
      </div>
    </body></html>
    """
    detail = parse_detail(html, "https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=1")
    assert detail.mall_url == "https://item.gmarket.co.kr/Item?goodscode=2713640571"


def test_enrich_from_rss_body():
    body = (
        '<img src="https://cdn.example.com/p.jpg">'
        '<a href="https://www.coupang.com/vp/products/1">buy</a>'
    )
    detail = enrich_from_list_body(body)
    assert detail.thumbnail_url == "https://cdn.example.com/p.jpg"
    assert detail.mall_url == "https://www.coupang.com/vp/products/1"


def test_quasarzone_v2_list_row():
    html = """
    <div class="v2-list-row v2-list-row--hotdeal" data-qc-id="1983943"
         data-preview="https://img2.quasarzone.com/a.webp?">
      <a href="/bbs/qb_saleinfo/views/1983943" class="subject-link">[지마켓] 필립스 모니터</a>
      <span class="v2-list-row__price">￦870,510원</span>
      <span class="ctn-count">1</span>
      <span class="qc-count-hit">218</span>
      <span class="v2-list-row__time">21분 전</span>
      <span data-nick="로젠CJ"></span>
    </div>
    <div class="v2-list-row" data-qc-id="1">
      <a href="/bbs/qb_saleinfo/views/1" class="subject-link">[기타] 핫딜 게시판 안내</a>
    </div>
    """
    posts = parse_list(html)
    assert len(posts) == 1
    assert posts[0].source_post_id == "1983943"
    assert "필립스" in posts[0].title
    assert "870,510" in posts[0].title
    assert posts[0].author == "로젠CJ"
    assert posts[0].comments == 1
    assert posts[0].extra["thumbnail_url"].startswith("https://img2.quasarzone.com/")


def test_quasarzone_prefers_href_id_over_data_qc_id():
    html = """
    <div class="v2-list-row v2-list-row--hotdeal" data-qc-id="999"
         data-preview="https://img2.quasarzone.com/qb_saleinfo/2020/12/05/dc9345db51f5b6aa0e363ed2cfbe9358.png">
      <a href="/bbs/qb_saleinfo/views/277137" class="subject-link">[롯데온] 사이버펑크 2077</a>
      <span class="v2-list-row__price">￦45,000원</span>
    </div>
    """
    posts = parse_list(html)
    assert len(posts) == 1
    assert posts[0].source_post_id == "277137"
    assert "사이버펑크" in posts[0].title
    assert not posts[0].extra.get("thumbnail_url")


def test_quasarzone_views_fallback():
    html = """
    <html><body>
      <a href="/bbs/qb_saleinfo/views/1982858">[네이버] 컬리N마트 1주년 100원딜</a>
      <a href="/bbs/qb_saleinfo/views/1982853" title="[지마켓] RTX 5080">다음</a>
    </body></html>
    """
    posts = parse_list(html)
    assert len(posts) >= 1
    assert posts[0].source_post_id == "1982858"
    assert "컬리" in posts[0].title
