from __future__ import annotations

import re
from dataclasses import dataclass

STOPWORDS = {
    "무료",
    "무배",
    "무료배송",
    "쿠폰",
    "할인",
    "특가",
    "핫딜",
    "오늘만",
    "한정",
    "카드",
    "적립",
    "최대",
    "즉시",
    "적용",
    "배송",
    "로켓",
    "와우",
    "멤버십",
    "네이버페이",
}

# seller aliases for later display only
SELLER_NORMALIZE = {
    "g마켓": "G마켓",
    "지마켓": "G마켓",
    "네이버스토어": "네이버",
    "스마트스토어": "네이버",
    "네이버쇼핑": "네이버",
    "쿠팡와우": "쿠팡",
    "11번가": "11번가",
    "ssg": "SSG",
    "롯데온": "롯데온",
}


@dataclass
class Quantity:
    grams: float | None = None
    milliliters: float | None = None
    count: float | None = None
    label: str | None = None


_Q_PATTERNS = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*kg", re.I), "kg"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*g(?![a-z])", re.I), "g"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:ml|㎖)", re.I), "ml"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:l|리터)(?![a-z])", re.I), "l"),
    (re.compile(r"(\d+)\s*(?:개입|입|개|매|롤|팩|포|장|병|캔|스틱|t)\b", re.I), "count"),
]


def extract_quantity(name: str) -> Quantity:
    text = name.lower().replace(" ", "")
    qty = Quantity()
    grams = 0.0
    ml = 0.0
    count = 0.0
    labels: list[str] = []
    for pat, kind in _Q_PATTERNS:
        for m in pat.finditer(text):
            val = float(m.group(1))
            labels.append(m.group(0))
            if kind == "kg":
                grams += val * 1000
            elif kind == "g":
                grams += val
            elif kind == "ml":
                ml += val
            elif kind == "l":
                ml += val * 1000
            elif kind == "count":
                count += val
    if grams:
        qty.grams = grams
    if ml:
        qty.milliliters = ml
    if count:
        qty.count = count
    qty.label = "+".join(labels[:4]) if labels else None
    return qty


def tokenize(name: str) -> set[str]:
    cleaned = re.sub(r"[\[\]()（）{}<>]", " ", name)
    cleaned = re.sub(r"[^0-9A-Za-z가-힣+\.]+", " ", cleaned)
    tokens: set[str] = set()
    for tok in cleaned.lower().split():
        if tok in STOPWORDS or len(tok) < 2:
            continue
        tok = re.sub(r"(\d+)(?:개입|입|t)$", r"\1개", tok, flags=re.I)
        tokens.add(tok)
    return tokens


def product_key(tokens: set[str]) -> str:
    if not tokens:
        return ""
    return "|".join(sorted(tokens))


def unit_price(price: int | None, qty: Quantity) -> float | None:
    if not price:
        return None
    if qty.grams and qty.grams > 0:
        return round(price / qty.grams * 10, 2)  # per 10g
    if qty.milliliters and qty.milliliters > 0:
        return round(price / qty.milliliters * 10, 2)  # per 10ml
    if qty.count and qty.count > 0:
        return round(price / qty.count, 2)
    return None


def canonical_seller(seller: str | None) -> str | None:
    if not seller:
        return None
    key = seller.strip().lower().replace(" ", "")
    return SELLER_NORMALIZE.get(key, seller.strip())
