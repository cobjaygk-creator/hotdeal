from app.engine.alerts import format_alert, grade_rank, keyword_tokens, matches_keyword, meets_min_grade


def test_grade_rank_order():
    assert grade_rank("🔥🔥🔥 초특가") > grade_rank("🔥🔥 특가") > grade_rank("🔥 핫딜")
    assert meets_min_grade("🔥 핫딜", "핫딜")
    assert meets_min_grade("🔥🔥 특가", "핫딜")
    assert not meets_min_grade("관심", "핫딜")
    assert not meets_min_grade("이력없음", "핫딜")
    assert meets_min_grade("관심", "관심")


def test_keyword_and_tokens():
    assert keyword_tokens(" 카누  미니 ") == ["카누", "미니"]
    deal = {"product_name": "카누 미니 마일드 120개입", "seller": "네이버"}
    assert matches_keyword(deal, "카누")
    assert matches_keyword(deal, "카누 미니")
    assert not matches_keyword(deal, "카누 스위치")
    assert not matches_keyword(deal, "")


def test_format_alert_contains_url_and_keyword():
    text = format_alert(
        {
            "id": 12,
            "product_name": "카누 미니",
            "seller": "네이버",
            "price": 36070,
            "discount_rate": 0.18,
            "grade": "🔥 핫딜",
            "mall_url": "https://example.com/buy",
        },
        "카누",
    )
    assert "카누 미니" in text
    assert "36,070원" in text
    assert "키워드: 카누" in text
    assert "/deal/12" in text
    assert "https://example.com/buy" in text
