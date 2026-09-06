from pathlib import Path

from app.family.dealink import parse_list
from app.family.parse import extract_brands, extract_entry_code, normalize_sale, parse_date_range, parse_discount, sale_status
from app.family import RawSale

SAMPLES = Path(__file__).resolve().parents[1] / "_samples"


def test_dealink_list():
    html = (SAMPLES / "dealink.html").read_text(encoding="utf-8", errors="replace")
    sales = parse_list(html)
    assert len(sales) >= 10
    assert all(s.source_post_id.isdigit() for s in sales)
    el = next(s for s in sales if "엘무드" in s.title)
    start, end = parse_date_range(el.date_range)
    assert start == "2026-08-27"
    assert end == "2026-09-04"
    n = normalize_sale(el)
    assert n["discount_max"] == 80
    assert "패션의류" in n["categories"]


def test_dealink_card_thumbnail():
    html = """
    <div class="swiper-slide-familysale">
      <ul class="gallery-item-img">
        <a href="https://dealink.co.kr/familysale/1200">
          <img src="https://dealink.co.kr/data/file/familysale/thumb-abc_202x150.jpg" alt="">
        </a>
      </ul>
      <ul class="gallery-item-info">패션↑</ul>
      <ul class="gallery-item-tit"><a href="https://dealink.co.kr/familysale/1200">엘무드 패밀리세일 (~80%)</a></ul>
      <ul class="gallery-item-date">2026-08-27 ~ 2026-09-04</ul>
    </div>
    """
    sales = parse_list(html)
    assert len(sales) == 1
    assert sales[0].thumbnail_url == "https://dealink.co.kr/data/file/familysale/thumb-abc_202x150.jpg"
    n = normalize_sale(sales[0])
    assert n["thumbnail_url"] == sales[0].thumbnail_url


def test_normalize_sale_thumbnail_passthrough():
    raw = RawSale(
        source_name="x", source_post_id="1", title="브랜드 패밀리세일 ~50%",
        source_url="https://x/1", thumbnail_url="  https://img/x.jpg  ",
    )
    assert normalize_sale(raw)["thumbnail_url"] == "https://img/x.jpg"
    raw2 = RawSale(source_name="x", source_post_id="2", title="t", source_url="https://x/2")
    assert normalize_sale(raw2)["thumbnail_url"] is None


def test_parse_helpers():
    assert parse_discount("네이밍 페스타 세일 ~89%", "최대 89%") == ("~89%", 89)
    brands = extract_brands("리바트 / 허레이 / 던스트", "브랜드데이")
    assert "리바트" in brands
    assert extract_entry_code("입장코드 : kreamhouse2026") == "kreamhouse2026"
    assert sale_status("2026-08-27", "2026-09-04").__class__ is str
