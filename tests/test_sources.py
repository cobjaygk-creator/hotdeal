from pathlib import Path

from app.sources.arca import parse_list as parse_arca
from app.sources.clien import parse_list as parse_clien
from app.sources.damoang import parse_rss as parse_damoang_rss
from app.sources.ppomppu import parse_list_html, parse_rss
from app.sources.quasarzone import parse_list as parse_quasar
from app.sources.ruliweb import parse_list as parse_ruliweb
from app.sources.coolenjoy import parse_rss as parse_coolenjoy_rss
from app.sources.dealbada import parse_list as parse_dealbada
from app.sources.eomisae import parse_list as parse_eomisae
from app.sources.fmkorea import parse_list as parse_fmkorea

SAMPLES = Path(__file__).resolve().parents[1] / "_samples"


def test_ppomppu_html():
    html = (SAMPLES / "ppomppu.html").read_bytes().decode("euc-kr", errors="replace")
    posts = parse_list_html(html)
    assert len(posts) >= 15
    assert all(p.source_post_id.isdigit() for p in posts)
    assert any(p.posted_at for p in posts)


def test_ppomppu_list_thumbnail_and_merge():
    from app.sources.ppomppu import merge_list_and_rss

    html = """
    <table>
      <tr class="baseList">
        <td class="baseList-numb">731058</td>
        <td><a class="baseList-title" href="#">[지오다노] 셔츠 (22,000원/무료)</a>
          <img src="//cdn2.ppomppu.co.kr/zboard/data/_thumb/ppomppu/8/small_731058.jpg?t=1">
          <img src="//cdn2.ppomppu.co.kr/images/menu/pop_icon2.jpg">
        </td>
        <td class="baseList-rec">1-0</td>
        <td class="baseList-views">10</td>
        <td title="26.09.02 12:33"><span class="baseList-name">u</span></td>
      </tr>
    </table>
    """
    posts = parse_list_html(html)
    assert len(posts) == 1
    assert posts[0].extra["thumbnail_url"].startswith(
        "https://cdn2.ppomppu.co.kr/zboard/data/_thumb/"
    )
    rss = parse_rss(
        """<?xml version="1.0"?><rss><channel><item>
        <title>[지오다노] 셔츠 (22,000원/무료)</title>
        <link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=731058</link>
        <description>본문 https://naver.me/xiL30JlA상품링크</description>
        <hits>[1|10|0|0]</hits>
        </item></channel></rss>"""
    )
    merged = merge_list_and_rss(posts, rss)
    assert merged[0].body and "naver.me" in merged[0].body
    assert merged[0].extra["thumbnail_url"]


def test_ppomppu_rss_sample():
    xml = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0"><channel>
    <item>
      <title>[네이버] 테스트 상품 (12,000원/무료)</title>
      <link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=123</link>
      <description>desc</description>
      <author>tester</author>
      <pubDate>Thu, 27 Aug 2026 04:43:53 GMT</pubDate>
      <hits> [1|89|0|0]</hits>
    </item>
    </channel></rss>
    """
    posts = parse_rss(xml)
    assert len(posts) == 1
    assert posts[0].source_post_id == "123"
    assert posts[0].votes == 1
    assert posts[0].views == 89
    assert posts[0].extra["thumbnail_url"] == (
        "https://cdn2.ppomppu.co.kr/zboard/data/_thumb/ppomppu/3/small_123.jpg"
    )


def test_other_html_parsers():
    arca = parse_arca((SAMPLES / "arca.html").read_text(encoding="utf-8", errors="replace"))
    assert len(arca) >= 10
    quasar = parse_quasar((SAMPLES / "quasar.html").read_text(encoding="utf-8", errors="replace"))
    assert len(quasar) >= 10
    clien = parse_clien((SAMPLES / "clien.html").read_text(encoding="utf-8", errors="replace"))
    assert len(clien) >= 10
    ruli = parse_ruliweb((SAMPLES / "ruliweb.html").read_text(encoding="utf-8", errors="replace"))
    assert len(ruli) >= 8


def test_damoang_rss_parser():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>아이즈 5G 150G 무제한 평생 24,900원</title>
        <link>https://damoang.net/economy/79924</link>
        <description>최저가 23,900원으로 1,000원 비쌉니다.</description>
        <author>예지</author>
        <pubDate>Fri, 04 Sep 2026 03:31:03 GMT</pubDate>
      </item>
      <item>
        <title>공지사항</title><link>https://damoang.net/notice/1</link>
      </item>
    </channel></rss>"""
    posts = parse_damoang_rss(xml)
    assert [p.source_post_id for p in posts] == ["79924"]
    p = posts[0]
    assert p.url == "https://damoang.net/economy/79924"
    assert "24,900원" in p.title and p.body and p.author == "예지"
    assert p.posted_at is not None


def test_coolenjoy_rss_parser():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>맥스엘리트 850W 골드 풀모듈러 외 다수</title>
        <link>https://coolenjoy.net/bbs/jirum/3552053</link>
        <description><![CDATA[<p>안녕하세요<img src="/data/editor/2609/abc.png" /></p>]]></description>
        <pubDate>Fri, 04 Sep 2026 02:00:00 GMT</pubDate>
      </item>
      <item><title>공지</title><link>https://coolenjoy.net/bbs/jirum/1</link></item>
    </channel></rss>"""
    posts = parse_coolenjoy_rss(xml)
    assert [p.source_post_id for p in posts] == ["3552053"]
    p = posts[0]
    assert p.url == "https://coolenjoy.net/bbs/jirum/3552053"
    assert p.extra["thumbnail_url"] == "https://coolenjoy.net/data/editor/2609/abc.png"
    assert p.body and p.posted_at is not None


def test_new_community_parsers():
    eomi = parse_eomisae((SAMPLES / "eomisae_fs.html").read_text(encoding="utf-8", errors="replace"))
    assert len(eomi) >= 5
    assert all("공지" not in (p.title or "") for p in eomi)

    deal = parse_dealbada((SAMPLES / "dealbada.html").read_text(encoding="utf-8", errors="replace"))
    assert len(deal) >= 8
    assert any("원" in p.title for p in deal)


def test_fmkorea_parser():
    html = """
    <ul>
      <li class="li">
        <a href="/10294415447"><img class="thumb" data-original="//image.fmkorea.com/filesn/t.webp" alt=""></a>
        <h3 class="title"><a href="/10294415447" class="hotdeal_var8">
          <span class="ellipsis-target">유한락스 욕실청소용 600ml</span>
        </a></h3>
        <div class="hotdeal_info">
          <span>쇼핑몰: <a class="strong">오늘의집</a></span>
          <span>가격: <a class="strong">11,340원</a></span>
          <span>배송: <a class="strong">무료</a></span>
        </div>
        <span class="regdate">08:54</span>
        <span class="author"> / 테스터</span>
      </li>
      <li class="li">
        <h3 class="title"><a href="/1"><span class="ellipsis-target">핫딜게시판 이용규칙</span></a></h3>
      </li>
    </ul>
    """
    posts = parse_fmkorea(html)
    assert len(posts) == 1
    assert posts[0].source == "fmkorea"
    assert posts[0].source_post_id == "10294415447"
    assert posts[0].url.endswith("/10294415447")
    assert "오늘의집" in posts[0].title
    assert "11,340원" in posts[0].title
    assert posts[0].author == "테스터"
    assert posts[0].extra["thumbnail_url"].startswith("https://image.fmkorea.com/")


def test_arca_list_thumbnail():
    html = """
    <div class="vrow hybrid">
      <a class="title hybrid-title" href="/b/hotdeal/181">콜라 제로</a>
      <span class="deal-price">12,990원</span>
      <span class="deal-delivery">무료</span>
      <a class="preview-image" href="/b/hotdeal/181">
        <img src="//ac.arca.live/x.jpg?type=list" loading="lazy" alt="">
      </a>
      <img src="/static/assets/images/shipping.svg" width="16">
    </div>
    """
    posts = parse_arca(html)
    assert len(posts) == 1
    assert posts[0].extra["thumbnail_url"].startswith("https://ac.arca.live/")


def test_eomisae_card_thumbnail():
    html = """
    <div class="card_el n_ntc clear">
      <div class="rt_area is_tmb">
        <div class="tmb_wrp">
          <img class="tmb" src="//img.eomisae.co.kr/files/thumbnails/1/2/3/190x190.crop.jpg" alt="">
        </div>
        <div class="card_content">
          <p><span class="cate">식품</span><span>26.09.04</span></p>
          <h3><a class="pjax" href="/fs/200123">콜라 제로 30개</a></h3>
        </div>
      </div>
    </div>
    """
    posts = parse_eomisae(html)
    assert len(posts) == 1
    assert posts[0].source_post_id == "200123"
    assert posts[0].extra["thumbnail_url"].startswith("https://img.eomisae.co.kr/")
    assert posts[0].extra["source_category"] == "식품"


def test_dealbada_list_thumbnail():
    html = """
    <table><tr>
      <td class="td_img"><img src="http://cdn.dealbada.com/data/editor/a.jpg" width="50"></td>
      <td class="td_subject">
        <a href="https://www.dealbada.com/bbs/board.php?bo_table=deal_domestic&wr_id=99">홍삼 세트</a>
      </td>
      <td class="td_date">09:00</td>
      <td class="td_num">10</td>
      <td class="td_num_g">1/0</td>
    </tr></table>
    """
    posts = parse_dealbada(html)
    assert len(posts) == 1
    assert posts[0].extra["thumbnail_url"] == "https://cdn.dealbada.com/data/editor/a.jpg"


def test_quasar_v2_rows_skip_partner_ads():
    """Partner rows link to /bbs/qb_partnersaleinfo/... and must not be minted
    as wrong-board qb_saleinfo URLs (their ids collide with real posts)."""
    html = """
    <div class="v2-list-row v2-list-row--hotdeal">
      <a class="v2-list-row__thumb img-background-wrap lazy" href="/bbs/qb_saleinfo/views/1984069"></a>
      <span class="v2-badge">PC/하드웨어</span>
      <a class="subject-link " href="/bbs/qb_saleinfo/views/1984069">[하이마트] MSI PRO B760M-A</a>
      <span class="v2-list-row__price">￦133,230</span>
      <span class="v2-list-row__time">39분 전</span>
    </div>
    <div class="v2-list-row v2-list-row--hotdeal v2-partner-row">
      <a class="v2-list-row__thumb img-background-wrap lazy" href="/bbs/qb_partnersaleinfo/views/277164"></a>
      <span class="v2-badge">파트너 핫딜</span>
      <a class="subject-link" href="/bbs/qb_partnersaleinfo/views/277164">[지마켓] 빅세일 특가</a>
      <span class="v2-list-row__price">￦305,396</span>
    </div>
    """
    posts = parse_quasar(html)
    assert [p.source_post_id for p in posts] == ["1984069"]
    assert posts[0].url == "https://quasarzone.com/bbs/qb_saleinfo/views/1984069"
    assert posts[0].extra["source_category"] == "PC/하드웨어"
