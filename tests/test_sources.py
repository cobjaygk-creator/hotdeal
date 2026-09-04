from pathlib import Path

from app.sources.arca import parse_list as parse_arca
from app.sources.clien import parse_list as parse_clien
from app.sources.damoang import parse_list as parse_damoang
from app.sources.ppomppu import parse_list_html, parse_rss
from app.sources.quasarzone import parse_list as parse_quasar
from app.sources.ruliweb import parse_list as parse_ruliweb
from app.sources.coolenjoy import parse_list as parse_coolenjoy
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
    damo = parse_damoang((SAMPLES / "damoang.html").read_text(encoding="utf-8", errors="replace"))
    assert len(damo) >= 8


def test_new_community_parsers():
    cool = parse_coolenjoy((SAMPLES / "coolenjoy.html").read_text(encoding="utf-8", errors="replace"))
    assert len(cool) >= 8
    assert all(p.source_post_id.isdigit() for p in cool)

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
