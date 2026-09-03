from app.engine.dedupe import is_same_deal, jaccard
from app.engine.pricing import compute_baseline, discount_rate
from app.engine.scoring import grade_from_discount, score_offer
from datetime import datetime, timezone

from app.parse.title import parse_title
from app.util.timeparse import format_clock, format_kst, format_relative


def test_format_kst():
    assert format_kst("2026-08-27 05:49:10") == "2026-08-27 14:49:10"
    assert format_kst(None) == "-"


def test_format_relative():
    now = datetime(2026, 8, 27, 6, 0, 0, tzinfo=timezone.utc)
    assert format_relative("2026-08-27 05:59:30", now=now) == "방금"
    assert format_relative("2026-08-27 05:48:00", now=now) == "12분전"
    assert format_relative("2026-08-27 03:00:00", now=now) == "3시간전"
    assert format_relative("2026-08-25 06:00:00", now=now) == "2일전"
    assert format_relative("2026-08-01 06:00:00", now=now) == "08-01"


def test_format_clock():
    assert format_clock("2026-08-27 05:49:10") == "14:49"
    assert format_clock(None) == ""


def test_primary_title():
    offer = parse_title("[네이버] 카누 미니 마일드로스트 120개입 (36,070원/무료)")
    assert offer.seller == "네이버"
    assert offer.price == 36070
    assert offer.shipping_free is True
    assert offer.shipping_fee == 0
    assert "카누" in offer.product_name
    assert offer.quantity.count == 120
    assert offer.confidence >= 0.9


def test_fallback_seller_paren():
    offer = parse_title("네이버) 플레이스 16종 상품 ~60%할인 (27,600원,무료)")
    assert offer.seller == "네이버"
    assert offer.price == 27600
    assert offer.shipping_free is True


def test_gmarket_and_unit_price():
    offer = parse_title("[G마켓] 새청무 쌀 10kg 특등급 (29,500원/무료)")
    assert offer.seller == "G마켓"
    assert offer.price == 29500
    assert offer.quantity.grams == 10000
    assert offer.unit_price == 29.5  # per 10g


def test_ruliweb_trailing_won():
    offer = parse_title("[알리] 앤커 프라임 보조배터리 151,829원")
    assert offer.seller == "알리"
    assert offer.price == 151829


def test_same_price_prefers_non_ppomppu_and_strips_noise():
    from app.engine.dedupe import collapse_duplicate_deals, prefers_non_ppomppu

    a = parse_title("삼다수 2L 24개 18,252원 - 기타정보")
    b = parse_title("삼다수 2L 24개")
    b.price = 18252
    assert "기타정보" not in a.product_name
    assert is_same_deal(a, b) is True
    assert prefers_non_ppomppu("eomisae", "ppomppu") is True
    assert prefers_non_ppomppu("ppomppu", "eomisae") is False
    collapsed = collapse_duplicate_deals(
        [
            {"id": 1, "product_name": a.product_name, "product_key": a.product_key, "price": 18252, "sources": "ppomppu"},
            {"id": 2, "product_name": b.product_name, "product_key": b.product_key, "price": 18252, "sources": "eomisae"},
        ]
    )
    assert len(collapsed) == 1
    assert collapsed[0]["sources"] == "eomisae"


def test_jaccard_and_dedupe():
    a = parse_title("[네이버] 카누 미니 마일드 120개입 (36070원/무료)")
    b = parse_title("[쿠팡] 카누 미니 마일드 120개입 (35500원/무배)")
    assert jaccard(a.tokens, b.tokens) >= 0.7
    assert is_same_deal(a, b) is True
    c = parse_title("[네이버] 휴지 30롤 (19800원/무료)")
    assert is_same_deal(a, c) is False


def test_baseline_median_and_grades():
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    prices = [
        (datetime(2026, 8, 20, tzinfo=timezone.utc), 44800),
        (datetime(2026, 8, 21, tzinfo=timezone.utc), 44800),
        (datetime(2026, 8, 22, tzinfo=timezone.utc), 43900),
        (datetime(2026, 8, 23, tzinfo=timezone.utc), 43900),
        (datetime(2026, 8, 24, tzinfo=timezone.utc), 42500),
        (datetime(2026, 8, 25, tzinfo=timezone.utc), 40900),
        (datetime(2026, 8, 26, tzinfo=timezone.utc), 44500),
    ]
    base = compute_baseline(prices, now=now)
    assert base.sample_count == 7
    assert base.median == 43900
    offer = parse_title("[네이버] 카누 미니 마일드로스트 120개입 (36,070원/무료)")
    disc = discount_rate(offer.price, base.median)
    assert disc is not None
    assert 0.15 <= disc < 0.20
    result = score_offer(offer, base, now=now)
    assert "핫딜" in result.grade
    assert result.suppress is False


def test_anomaly_and_cooldown():
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    prices = [(datetime(2026, 8, d, tzinfo=timezone.utc), 40000) for d in range(10, 20)]
    base = compute_baseline(prices, now=now)
    cheap = parse_title("[네이버] 카누 미니 120개입 (1,000원/무료)")
    result = score_offer(cheap, base, now=now)
    assert result.status == "needs_review"
    normal = parse_title("[네이버] 카누 미니 120개입 (36,070원/무료)")
    first = score_offer(normal, base, now=now)
    again = score_offer(
        normal,
        base,
        now=now,
        last_scored_at=now,
        last_scored_price=36070,
    )
    assert first.suppress is False
    assert again.suppress is True
    lower = parse_title("[네이버] 카누 미니 120개입 (33,000원/무료)")
    dropped = score_offer(
        lower,
        base,
        now=now,
        last_scored_at=now,
        last_scored_price=36070,
    )
    assert dropped.suppress is False


def test_grade_buckets():
    assert grade_from_discount(0.05) == "일반"
    assert grade_from_discount(0.12) == "관심"
    assert "핫딜" in grade_from_discount(0.18)
    assert "특가" in grade_from_discount(0.22)
    assert "초특가" in grade_from_discount(0.31)


def test_truncated_title_drops_price():
    offer = parse_title("[네이버] BOSE QC 울트라 이어버드 2세대 색상 다양 / 273,6...")
    assert offer.price is None
    assert "273" not in offer.product_key
    assert "bose" in offer.product_key


def test_reject_sub_1000_price():
    offer = parse_title("[딜바다] 테스트 상품 (500원/무료)")
    assert offer.price is None
