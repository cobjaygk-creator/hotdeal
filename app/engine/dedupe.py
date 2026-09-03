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
    pa = price_a or offer_a.price
    pb = price_b or offer_b.price
    if offer_a.product_key == offer_b.product_key:
        return _price_close(pa, pb)
    if not _price_close(pa, pb):
        return False
    return _tokens_aligned(offer_a.tokens, offer_b.tokens)


def _tokens_aligned(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    if jaccard(a, b) >= JACCARD_THRESHOLD:
        return True
    # 같은 가격이면 "삼다수 2L 24개" vs "삼다수 2L 24개 기타정보"처럼
    # 짧은 쪽 토큰이 긴 쪽에 다 들어가면 같은 딜로 본다.
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 2 and shorter <= longer:
        return True
    return jaccard(a, b) >= 0.55


def prefers_non_ppomppu(incoming_source: str | None, existing_sources: list[str] | str | None) -> bool:
    """표시용 필드(제목·원문 링크)는 뽐뿌가 아닌 출처를 남긴다."""
    incoming = (incoming_source or "").strip().lower()
    if isinstance(existing_sources, str):
        existing = [s.strip().lower() for s in existing_sources.split(",") if s.strip()]
    else:
        existing = [str(s).strip().lower() for s in (existing_sources or []) if s]
    existing_has_other = any(s and s != "ppomppu" for s in existing)
    if incoming and incoming != "ppomppu":
        return True
    return not existing_has_other


def collapse_duplicate_deals(deals: list[dict]) -> list[dict]:
    """목록에서 같은 가격·비슷한 제목을 한 장으로 접고 비뽐뿌를 남긴다."""
    kept: list[dict] = []
    for deal in deals:
        dup = None
        for prev in kept:
            if _list_items_same(deal, prev):
                dup = prev
                break
        if dup is None:
            kept.append(deal)
            continue
        if _deal_source_rank(deal) < _deal_source_rank(dup):
            kept[kept.index(dup)] = deal
    return kept


def _list_items_same(a: dict, b: dict) -> bool:
    if not _price_close(a.get("price"), b.get("price")):
        return False
    ta = set((a.get("product_key") or "").split("|")) - {""}
    tb = set((b.get("product_key") or "").split("|")) - {""}
    if ta and tb:
        return _tokens_aligned(ta, tb)
    from app.parse.normalize import tokenize

    return _tokens_aligned(tokenize(a.get("product_name") or ""), tokenize(b.get("product_name") or ""))


def _deal_source_rank(deal: dict) -> int:
    raw = deal.get("sources") or ""
    keys = [s.strip().lower() for s in str(raw).split(",") if s.strip()]
    if any(k != "ppomppu" for k in keys):
        return 0
    return 1


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
