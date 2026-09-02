from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.amazon_jp import RawAmazonDeal
from app.http_client import PoliteClient

LIST_URL = "https://mottoku.app/deals?source=amazon&min_discount=30&sort=discount&p={page}"
ASIN_RE = re.compile(r"/a/([A-Z0-9]{10})", re.I)
YEN_RE = re.compile(r"([\d,]+)")
PCT_RE = re.compile(r"(\d+)")
MIN_DISCOUNT = 0.30
MIN_YEN = 1000
MAX_PAGES = 3


class MottokuAmazonSource:
    name = "mottoku"

    async def fetch_latest(self, client: PoliteClient) -> list[RawAmazonDeal]:
        deals: list[RawAmazonDeal] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            result = await client.get(LIST_URL.format(page=page))
            if result.not_modified:
                continue
            if result.status >= 400 or not result.text:
                break
            batch = parse_list(result.text)
            if not batch:
                break
            for deal in batch:
                if deal.asin in seen:
                    continue
                seen.add(deal.asin)
                deals.append(deal)
            if len(batch) < 10:
                break
        return deals


def parse_list(html: str) -> list[RawAmazonDeal]:
    tree = HTMLParser(html)
    deals: list[RawAmazonDeal] = []
    seen: set[str] = set()
    for wrap in tree.css("div.deal-card-wrap"):
        deal = _parse_card(wrap)
        if deal is None or deal.asin in seen:
            continue
        seen.add(deal.asin)
        deals.append(deal)
    return deals


def _parse_card(wrap) -> RawAmazonDeal | None:
    fav = wrap.css_first("button.deal-card-fav")
    source = (fav.attributes.get("data-fav-source") or "").strip().lower() if fav else ""
    badge = wrap.css_first(".deal-card-badge")
    badge_text = " ".join((badge.text() or "").split()).lower() if badge else ""
    if source != "amazon" and "amazon" not in badge_text:
        return None

    link = wrap.css_first("a.deal-card")
    href = (link.attributes.get("href") if link else None) or ""
    asin = ""
    if fav:
        asin = _asin_from(fav.attributes.get("data-fav-path") or "")
    if not asin:
        asin = _asin_from(href)
    if not asin:
        return None

    name_el = wrap.css_first("h3.deal-card-name")
    title = " ".join((name_el.text() or "").split()) if name_el else ""
    if fav and not title:
        title = (fav.attributes.get("data-fav-name") or "").strip()
    if not title:
        return None

    yen_price = None
    if fav:
        yen_price = _to_int(fav.attributes.get("data-fav-price"))
    if yen_price is None:
        current = wrap.css_first(".deal-card-current")
        yen_price = _yen(current.text() if current else None)
    if yen_price is None or yen_price < MIN_YEN:
        return None

    original = None
    orig_el = wrap.css_first(".deal-card-original")
    if orig_el:
        original = _yen(orig_el.text())

    disc_el = wrap.css_first(".deal-card-discount")
    discount = _pct(disc_el.text() if disc_el else None)
    if discount is None and original and original > yen_price:
        discount = (original - yen_price) / original
    if discount is None or discount < MIN_DISCOUNT:
        return None

    image_url = None
    img = wrap.css_first(".deal-card-image img")
    if img:
        image_url = (img.attributes.get("src") or "").strip() or None
    if not image_url and fav:
        image_url = (fav.attributes.get("data-fav-image") or "").strip() or None

    updated_el = wrap.css_first(".deal-card-updated")
    updated = " ".join((updated_el.text() or "").split()) if updated_el else None

    return RawAmazonDeal(
        asin=asin.upper(),
        title=title,
        yen_price=yen_price,
        original_yen=original,
        discount_rate=round(discount, 4),
        image_url=image_url,
        source="mottoku",
        source_url=urljoin("https://mottoku.app/", href or f"/a/{asin}"),
        source_updated_at=updated,
    )


def _asin_from(path: str) -> str:
    m = ASIN_RE.search(path or "")
    return m.group(1).upper() if m else ""


def _to_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = re.sub(r"[^\d]", "", str(raw))
    return int(digits) if digits else None


def _yen(text: str | None) -> int | None:
    if not text:
        return None
    m = YEN_RE.search(text.replace(",", ""))
    if not m:
        m = YEN_RE.search(text)
    return _to_int(m.group(1) if m else text)


def _pct(text: str | None) -> float | None:
    if not text:
        return None
    m = PCT_RE.search(text)
    if not m:
        return None
    n = int(m.group(1))
    if n > 100:
        return None
    return n / 100.0
