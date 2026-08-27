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


def test_parse_helpers():
    assert parse_discount("네이밍 페스타 세일 ~89%", "최대 89%") == ("~89%", 89)
    brands = extract_brands("리바트 / 허레이 / 던스트", "브랜드데이")
    assert "리바트" in brands
    assert extract_entry_code("입장코드 : kreamhouse2026") == "kreamhouse2026"
    assert sale_status("2026-08-27", "2026-09-04").__class__ is str
