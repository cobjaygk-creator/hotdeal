from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import DEDUPE_HOURS, JACCARD_THRESHOLD, PRICE_DELTA
from app.parse.title import ParsedOffer


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def is_same_deal(
    offer_a: ParsedOffer,
    offer_b: ParsedOffer,
    price_a: int | None = None,
    price_b: int | None = None,
) -> bool:
    if not offer_a.product_key or not offer_b.product_key:
        return False
    if offer_a.product_key == offer_b.product_key:
        return _price_close(price_a or offer_a.price, price_b or offer_b.price)
    if jaccard(offer_a.tokens, offer_b.tokens) < JACCARD_THRESHOLD:
        return False
    return _price_close(price_a or offer_a.price, price_b or offer_b.price)


def _price_close(a: int | None, b: int | None) -> bool:
    if not a or not b:
        return True
    hi, lo = (a, b) if a >= b else (b, a)
    return (hi - lo) / hi <= PRICE_DELTA


def within_window(posted_at: datetime | None, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if posted_at is None:
        return True
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return posted_at >= now - timedelta(hours=DEDUPE_HOURS)


def should_merge(offer: ParsedOffer, existing: dict) -> bool:
    """existing keys: product_key, tokens, price, last_seen_at."""
    other = ParsedOffer(
        seller=existing.get("seller"),
        product_name=existing.get("product_name") or "",
        price=existing.get("price"),
        shipping_fee=existing.get("shipping_fee"),
        shipping_free=False,
        tokens=set(existing.get("tokens") or []),
        product_key=existing.get("product_key") or "",
        quantity=offer.quantity,
        unit_price=existing.get("unit_price"),
        confidence=1.0,
    )
    if existing.get("tokens") is None and other.product_key:
        other.tokens = set(other.product_key.split("|"))
    last_seen = existing.get("last_seen_at")
    seen_dt = None
    if isinstance(last_seen, datetime):
        seen_dt = last_seen
    elif isinstance(last_seen, str) and last_seen:
        try:
            seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
        except ValueError:
            seen_dt = None
    if seen_dt and not within_window(seen_dt):
        return False
    return is_same_deal(offer, other)
