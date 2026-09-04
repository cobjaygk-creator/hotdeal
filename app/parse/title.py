from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import MIN_SANE_PRICE
from app.parse.normalize import (
    Quantity,
    canonical_seller,
    extract_quantity,
    product_key,
    tokenize,
    unit_price,
)

PRIMARY = re.compile(
    r"^\[(?P<seller>[^\]]+)\]\s*(?P<name>.+?)\s*[\(（](?P<price>[^()（）]*)[\)）]\s*$"
)
FALLBACK_PAREN_SELLER = re.compile(
    r"^(?P<seller>[^)\[\]]{1,20})\)\s*(?P<name>.+?)\s*[\(（](?P<price>[^()（）]*)[\)）]\s*$"
)
BRACKET_THEN_WON = re.compile(
    r"^\[(?P<seller>[^\]]+)\]\s*(?P<name>.+?)\s+(?P<price>\d[\d,]*)\s*원"
)
ANY_WON = re.compile(r"(\d[\d,]*)\s*원")
FREE_SHIP = re.compile(r"(무료배송|무료|무배|무배송)")
TRUNCATED = re.compile(r"(?:\.{2,}|…)\s*$")


@dataclass
class ParsedOffer:
    seller: str | None
    product_name: str
    price: int | None
    shipping_fee: int | None
    shipping_free: bool
    tokens: set[str]
    product_key: str
    quantity: Quantity
    unit_price: float | None
    confidence: float
    raw_price_text: str | None = None


def parse_title(title: str) -> ParsedOffer:
    title = clean_deal_title(title)
    truncated = bool(TRUNCATED.search(title))
    seller, name, price_blob, conf = _split(title)
    price, shipping_fee, shipping_free, raw = _parse_price_blob(price_blob, title)
    if price is None and not truncated:
        m = ANY_WON.findall(title)
        if m:
            price = _to_int(m[-1])
            raw = m[-1] + "원"
            conf = max(conf - 0.15, 0.4)
    if truncated:
        # List pages often cut mid-price ("273,6..."); wait for detail enrich.
        price = None
        raw = None
        conf = min(conf, 0.45)
    if price is not None and price < MIN_SANE_PRICE:
        price = None
        conf = min(conf, 0.35)
    if not name:
        name = title
    name = re.sub(r"\s+\d[\d,]*\s*원\s*$", "", name)
    name = re.sub(r"\s*[-–]\s*(기타정보|인기정보)\s*$", "", name)
    qty = extract_quantity(name)
    tokens = tokenize(name)
    return ParsedOffer(
        seller=canonical_seller(seller),
        product_name=name.strip(),
        price=price,
        shipping_fee=shipping_fee,
        shipping_free=shipping_free,
        tokens=tokens,
        product_key=product_key(tokens),
        quantity=qty,
        unit_price=unit_price(price, qty),
        confidence=conf if price else min(conf, 0.35),
        raw_price_text=raw,
    )


def clean_deal_title(title: str) -> str:
    title = (title or "").strip()
    title = re.sub(r"^(출석|정보|공지|이벤트)\s+", "", title)
    # Dealbada list subjects: "딜바다::[쿠팡] … > 국내핫딜"
    title = re.sub(r"^딜바다\s*::\s*", "", title, flags=re.I)
    title = re.sub(r"\s*>\s*(국내핫딜|해외핫딜|기타정보|인기정보)\s*$", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def _split(title: str) -> tuple[str | None, str, str | None, float]:
    for pat, conf in ((PRIMARY, 0.95), (FALLBACK_PAREN_SELLER, 0.85), (BRACKET_THEN_WON, 0.8)):
        m = pat.match(title)
        if m:
            return (
                m.group("seller").strip(),
                m.group("name").strip(),
                m.group("price").strip(),
                conf,
            )
    m = re.match(r"^\[(?P<seller>[^\]]+)\]\s*(?P<name>.+)$", title)
    if m:
        return m.group("seller").strip(), m.group("name").strip(), None, 0.6
    return None, title, None, 0.4


def _parse_price_blob(
    blob: str | None, full: str
) -> tuple[int | None, int | None, bool, str | None]:
    shipping_free = bool(FREE_SHIP.search(full))
    if not blob:
        return None, None, shipping_free, None
    parts = re.split(r"[/／]", blob)
    price = _first_amount(parts[0]) if parts else None
    shipping_fee = None
    if len(parts) > 1:
        rest = parts[1]
        if FREE_SHIP.search(rest):
            shipping_free = True
            shipping_fee = 0
        else:
            shipping_fee = _first_amount(rest)
    return price, shipping_fee, shipping_free, blob


def _first_amount(text: str) -> int | None:
    m = re.search(r"\d[\d,]*", text)
    if not m:
        return None
    return _to_int(m.group(0))


def _to_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    return int(digits)
