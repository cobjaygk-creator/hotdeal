"""Infer display mall name / key from a shop URL host."""
from __future__ import annotations

from urllib.parse import urlparse

# (host needle, display label, css data-mall key)
_MALL_HOSTS: tuple[tuple[str, str, str], ...] = (
    ("coupa.ng", "쿠팡", "coupang"),
    ("link.coupang.com", "쿠팡", "coupang"),
    ("coupang.com", "쿠팡", "coupang"),
    ("smartstore.naver.com", "네이버", "naver"),
    ("brand.naver.com", "네이버", "naver"),
    ("shopping.naver.com", "네이버", "naver"),
    ("m.shopping.naver.com", "네이버", "naver"),
    ("naver.me", "네이버", "naver"),
    ("gmarket.co.kr", "G마켓", "gmarket"),
    ("gma.me", "G마켓", "gmarket"),
    ("auction.co.kr", "옥션", "auction"),
    ("11st.co.kr", "11번가", "11st"),
    ("11st.kr", "11번가", "11st"),
    ("ssg.com", "SSG", "ssg"),
    ("lotteon.com", "롯데온", "lotteon"),
    ("elm.lotte.com", "롯데온", "lotteon"),
    ("lotteimall.com", "롯데홈쇼핑", "lotte"),
    ("kurly.com", "컬리", "kurly"),
    ("oliveyoung.co.kr", "올리브영", "oliveyoung"),
    ("hmall.com", "현대Hmall", "hmall"),
    ("gsshop.com", "GS샵", "gsshop"),
    ("cjmall.com", "CJ온스타일", "cjmall"),
    ("nsmall.com", "NS홈쇼핑", "nsmall"),
    ("musinsa.com", "무신사", "musinsa"),
    ("29cm.co.kr", "29CM", "29cm"),
    ("wconcept.co.kr", "W컨셉", "wconcept"),
    ("ably.co.kr", "에이블리", "ably"),
    ("zigzag.kr", "지그재그", "zigzag"),
    ("kream.co.kr", "크림", "kream"),
    ("ohou.se", "오늘의집", "ohouse"),
    ("store.kakao.com", "카카오톡스토어", "kakao"),
    ("gift.kakao.com", "카카오톡선물하기", "kakao"),
    ("temu.com", "테무", "temu"),
    ("aliexpress.com", "알리익스프레스", "ali"),
    ("amazon.", "아마존", "amazon"),
    ("iherb.com", "아이허브", "iherb"),
    ("qoo10.", "Qoo10", "qoo10"),
    ("yes24.com", "예스24", "yes24"),
    ("kyobobook.co.kr", "교보문고", "kyobo"),
    ("shop.samsung.com", "삼성닷컴", "samsung"),
    ("e-himart.co.kr", "하이마트", "himart"),
    ("himart.co.kr", "하이마트", "himart"),
    ("homeplus.co.kr", "홈플러스", "homeplus"),
)


def mall_from_url(url: str | None) -> tuple[str | None, str | None]:
    """Return (display_label, css_key) inferred from mall_url host."""
    raw = (url or "").strip()
    if not raw:
        return None, None
    try:
        host = (urlparse(raw).hostname or "").lower()
    except ValueError:
        return None, None
    if not host:
        return None, None
    for needle, label, key in _MALL_HOSTS:
        if needle.endswith(".") and needle in host:
            return label, key
        if host == needle or host.endswith("." + needle) or needle in host:
            return label, key
    return None, None


def mall_label_from_url(url: str | None) -> str | None:
    return mall_from_url(url)[0]


def mall_key_from_url(url: str | None) -> str | None:
    return mall_from_url(url)[1]
