import re

from app.coupang import api
from app.coupang.golden_box import _to_raw


def test_signed_headers_shape(monkeypatch):
    monkeypatch.setattr(api, "COUPANG_PARTNERS_ACCESS_KEY", "AK-test")
    monkeypatch.setattr(api, "COUPANG_PARTNERS_SECRET_KEY", "SK-test")
    headers = api.signed_headers("POST", api.DEEPLINK_PATH)
    assert headers["Content-Type"] == "application/json"
    auth = headers["Authorization"]
    assert auth.startswith("CEA algorithm=HmacSHA256, ")
    assert "access-key=AK-test" in auth
    m = re.search(r"signed-date=(\d{6}T\d{6}Z)", auth)
    assert m, auth
    assert re.search(r"signature=[0-9a-f]{64}$", auth), auth


def test_signature_is_deterministic_for_fixed_date(monkeypatch):
    monkeypatch.setattr(api, "COUPANG_PARTNERS_ACCESS_KEY", "AK")
    monkeypatch.setattr(api, "COUPANG_PARTNERS_SECRET_KEY", "SK")
    monkeypatch.setattr(api, "_signed_date", lambda: "240101T000000Z")
    a = api.signed_headers("GET", "/x?y=1")["Authorization"]
    b = api.signed_headers("GET", "/x?y=1")["Authorization"]
    assert a == b
    assert api.signed_headers("GET", "/x?y=2")["Authorization"] != a


def test_is_coupang_product_url():
    assert api.is_coupang_product_url("https://www.coupang.com/vp/products/1")
    assert api.is_coupang_product_url("https://link.coupang.com/a/abc")
    assert not api.is_coupang_product_url("https://www.naver.com/x")
    assert not api.is_coupang_product_url("not a url")


def test_golden_box_to_raw_computes_discount():
    raw = _to_raw(
        {
            "productId": "123",
            "productName": "  테스트 상품 ",
            "productPrice": 8000,
            "basePrice": 10000,
            "productImage": "https://img/x.jpg",
            "productUrl": "https://www.coupang.com/vp/products/123",
        },
        "1001",
    )
    assert raw is not None
    assert raw.title == "테스트 상품"
    assert raw.discount_rate == 0.2
    assert _to_raw({"productName": "x"}, "1001") is None
