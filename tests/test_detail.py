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


def test_parse_detail_fmkorea_bd_capture_over_link_xe_content():
    """Stray .xe_content (관련링크) must not beat #bd_capture body."""
    html = """
    <html><head>
      <meta property="og:title" content="[알리] 코인 호주산 LA갈비 1kg+1kg 총 2kg - 에펨코리아">
      <meta property="og:image" content="https://image.fmkorea.com/filesn/a.webp">
    </head><body>
      <div class="xe_content">
        <a href="https://ko.aliexpress.com/item/1005009782228283.html">
          https://ko.aliexpress.com/item/1005009782228283.html
        </a>
      </div>
      <div id="bd_capture">
        <div class="xe_content">
          <img src="https://image.fmkorea.com/filesn/deal.jpg" alt="">
          <p>1kg씩 따로 소분돼 있어서 먹을 만큼씩 꺼내기 편함</p>
          <p>코인 6%에 YUAG03 선착순 쿠폰 먹이면 43,286원이고 1kg당 21,643원 나옴</p>
          <a href="https://ko.aliexpress.com/item/1005009782228283.html">구매</a>
        </div>
      </div>
    </body></html>
    """
    detail = parse_detail(html, "https://www.fmkorea.com/10295340047")
    assert detail.mall_url and "aliexpress.com" in detail.mall_url
    assert detail.body_html
    assert "소분돼" in detail.body_html
    assert "YUAG03" in detail.body_html
    assert "image.fmkorea.com/filesn/deal.jpg" in detail.body_html
    # Must not be link-only.
    assert "소분" in detail.body_html or "YUAG03" in detail.body_html
    assert detail.body_html.count("<a ") <= 2


def test_parse_detail_fmkorea_excludes_hotdeal_field_table():
    """Real FMKorea layout: .rd_hd holds the 링크/쇼핑몰/상품명/가격/배송
    hotdeal_table; body_html must carry only the article image + description."""
    html = """
    <html><head>
      <meta property="og:image" content="https://image.fmkorea.com/filesn/thumb.jpg">
    </head><body>
      <div id="bd_capture">
        <div class="rd_hd clear">
          <div class="board clear">
            <table class="hotdeal_table"><tbody>
              <tr><th scope="row">링크</th><td><div class="xe_content">
                <a href="https://smartstore.naver.com/mulhana/products/11162891811" class="hotdeal_url">https://smartstore.naver.com/mulhana/products/11162891811</a>
              </div></td></tr>
              <tr><th scope="row">쇼핑몰</th><td><div class="xe_content">네이버 </div></td></tr>
              <tr><th scope="row">상품명</th><td><div class="xe_content">프레시웰 500ml X 80개</div></td></tr>
              <tr><th scope="row">가격</th><td><div class="xe_content">13,490원</div></td></tr>
              <tr><th scope="row">배송</th><td><div class="xe_content">무료</div></td></tr>
            </tbody></table>
          </div>
          <div class="rd_nav_side"><a class="scrap">스크랩</a></div>
        </div>
        <div class="rd_body clear">
          <div class="document_address"><a href="/10296126521">https://www.fmkorea.com/10296126521</a></div>
          <article><div class="document_1_2 xe_content">
            <p><img src="https://image.fmkorea.com/filesn/water.jpg.webp" alt=""></p>
            <p>500ml로 휴대하면서 마시기 편함</p>
            <p>유라벨/무라벨 랜덤 발송인점 참고</p>
          </div></article>
        </div>
      </div>
    </body></html>
    """
    detail = parse_detail(html, "https://www.fmkorea.com/10296126521")
    assert detail.body_html
    assert "휴대하면서 마시기 편함" in detail.body_html
    assert "유라벨/무라벨 랜덤 발송인점 참고" in detail.body_html
    assert "image.fmkorea.com/filesn/water.jpg" in detail.body_html
    # Structured fields stay out of the body.
    assert "프레시웰 500ml X 80개" not in detail.body_html
    assert "13,490원" not in detail.body_html
    assert "무료" not in detail.body_html
    assert "smartstore.naver.com/mulhana" not in detail.body_html
    assert "<table" not in detail.body_html.lower()
    # ...but the link field still feeds mall_url.
    assert detail.mall_url == "https://smartstore.naver.com/mulhana/products/11162891811"


def test_parse_detail_fmkorea_picks_richest_xe_content():
    """Without #bd_capture, prefer the .xe_content with prose+images."""
    html = """
    <html><body>
      <div class="xe_content">
        <a href="https://ko.aliexpress.com/item/1.html">https://ko.aliexpress.com/item/1.html</a>
      </div>
      <div class="xe_content">
        <img data-original="//image.fmkorea.com/filesn/big.webp">
        <p>1kg씩 따로 소분돼 있어서 먹을 만큼씩 꺼내기 편함</p>
      </div>
    </body></html>
    """
    detail = parse_detail(html, "https://www.fmkorea.com/1")
    assert detail.body_html
    assert "소분돼" in detail.body_html
    assert "image.fmkorea.com/filesn/big.webp" in detail.body_html


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


def test_thin_body_html_helpers():
    from app.parse.sanitize_html import is_thin_body_html, prefers_body_html

    link_only = (
        '<a href="https://ko.aliexpress.com/item/1.html" target="_blank" '
        'rel="noopener noreferrer">https://ko.aliexpress.com/item/1.html</a>'
    )
    rich = "<p>1kg씩 따로 소분돼 있어서 먹을 만큼씩 꺼내기 편함</p><img src=\"https://cdn.example.com/a.jpg\">"
    assert is_thin_body_html(None)
    assert is_thin_body_html("")
    assert is_thin_body_html(link_only)
    assert not is_thin_body_html(rich)
    assert prefers_body_html(rich, link_only)
    assert not prefers_body_html(link_only, rich)



def test_strip_board_chrome():
    from app.parse.sanitize_html import strip_board_chrome

    # Class-stripped FMKorea body: header + hotdeal_table + nav, no real content.
    chrome_only = (
        "<div><div><span>2026.09.04 12:57</span><h1><span>[쿠팡] 사이다</span></h1></div>"
        "<div><span><img src=\"https://image.fmkorea.com/modules/point/icons/21.png\">믜믜지</span></div>"
        "<div><span>조회 수 <b>4727</b></span><span>추천 수 <b>4</b></span><span>댓글 <b>7</b></span></div></div>"
        "<table><tbody><tr><th>링크</th><td><a href=\"https://link.coupang.com/a/x\">x</a></td></tr>"
        "<tr><th>쇼핑몰</th><td>쿠팡</td></tr><tr><th>상품명</th><td>사이다</td></tr>"
        "<tr><th>가격</th><td>25,920원</td></tr><tr><th>배송</th><td>무료</td></tr></tbody></table>"
        "<div><span>위로</span><span>아래로</span><span>스크랩</span></div>"
    )
    assert strip_board_chrome(chrome_only) is None

    mixed = chrome_only + "<p>실제 본문 설명 여러 줄입니다</p><p><img src=\"https://image.fmkorea.com/files/attach/deal.jpg\"></p>"
    out = strip_board_chrome(mixed)
    assert out and "실제 본문 설명" in out and "deal.jpg" in out
    assert "링크" not in out and "조회 수" not in out and "믜믜지" not in out
    assert "<table" not in out and "<h1" not in out

    clean = "<p><img src=\"https://image.fmkorea.com/files/x.webp\"></p><p>휴대하기 편함</p>"
    assert strip_board_chrome(clean) == clean


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
