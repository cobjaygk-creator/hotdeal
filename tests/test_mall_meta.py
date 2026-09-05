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


def test_mall_kakao_store_labeled_talkdeal():
    assert mall_from_url("https://store.kakao.com/x/products/1") == ("톡딜", "kakao")
    assert mall_from_url("https://gift.kakao.com/product/1") == ("카카오톡선물하기", "kakao")


def test_mall_toss_and_steam():
    assert mall_from_url("https://toss.im/shopping/products/1") == ("토스", "toss")
    assert mall_from_url("https://store.steampowered.com/app/123") == ("스팀", "steam")


def test_mall_guess_from_unknown_host():
    label, key = mall_from_url("https://www.seorincomputer.co.kr/shop/system_detail.html?sid=1")
    assert label == "Seorincomputer"
    assert key == "guess-seorincomputer"
    assert mall_from_url("https://item.examplebrand.co.kr/product/99")[0] == "Examplebrand"
