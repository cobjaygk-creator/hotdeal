from app.parse.mall import mall_from_url, mall_label_from_url
from app.parse.title import clean_deal_title, parse_title


def test_clean_dealbada_prefix():
    raw = "딜바다::[지마켓] 뷰카 아쿠아민트 4개 (9,950원/무배) > 국내핫딜"
    assert clean_deal_title(raw) == "[지마켓] 뷰카 아쿠아민트 4개 (9,950원/무배)"
    offer = parse_title(raw)
    assert offer.seller == "G마켓"
    assert "딜바다" not in offer.product_name
    assert "국내핫딜" not in offer.product_name
    assert offer.price == 9950


def test_mall_from_url():
    assert mall_label_from_url("https://www.coupang.com/vp/products/1") == "쿠팡"
    assert mall_from_url("https://item.gmarket.co.kr/Item?goodscode=1") == ("G마켓", "gmarket")
    assert mall_from_url("https://brand.naver.com/x/products/1") == ("네이버", "naver")
    assert mall_from_url(None) == (None, None)
