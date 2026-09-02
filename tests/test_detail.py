from app.sources.detail import parse_detail
from app.sources.quasarzone import parse_list


def test_parse_detail_og_and_mall():
    html = """
    <html><head>
      <meta property="og:title" content="[쿠팡] 테스트 상품 (12,000원/무료)">
      <meta property="og:image" content="https://cdn.example.com/a.jpg">
    </head><body>
      <div class="board-contents">
        <a href="https://www.coupang.com/vp/products/99">구매</a>
        <img src="https://cdn.example.com/b.jpg">
      </div>
    </body></html>
    """
    detail = parse_detail(html, "https://example.com/post/1")
    assert detail.title and "테스트 상품" in detail.title
    assert detail.thumbnail_url == "https://cdn.example.com/a.jpg"
    assert detail.mall_url == "https://www.coupang.com/vp/products/99"


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
