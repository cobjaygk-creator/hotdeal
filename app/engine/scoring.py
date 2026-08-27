from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import (
    ANOMALY_DROP_RATIO,
    COOLDOWN_HOURS,
    MIN_SANE_PRICE,
)
from app.engine.pricing import Baseline, discount_rate
from app.parse.title import ParsedOffer


@dataclass
class ScoreResult:
    grade: str
    status: str
    score: float
    discount: float | None
    suppress: bool


def grade_from_discount(rate: float | None) -> str:
    if rate is None:
        return "이력없음"
    pct = rate * 100
    if pct >= 30:
        return "🔥🔥🔥 초특가"
    if pct >= 20:
        return "🔥🔥 특가"
    if pct >= 15:
        return "🔥 핫딜"
    if pct >= 10:
        return "관심"
    return "일반"


def score_offer(
    offer: ParsedOffer,
    baseline: Baseline,
    *,
    source_count: int = 1,
    votes: int = 0,
    last_scored_at: datetime | None = None,
    last_scored_price: int | None = None,
    now: datetime | None = None,
) -> ScoreResult:
    now = now or datetime.now(timezone.utc)
    disc = discount_rate(offer.price, baseline.median)
    status = "ok"
    suppress = False

    if offer.price is None or offer.confidence < 0.45:
        return ScoreResult("확인필요", "needs_review", 0, disc, False)

    if offer.price < MIN_SANE_PRICE:
        status = "needs_review"
    if (
        offer.shipping_fee is not None
        and offer.price
        and offer.shipping_fee > offer.price
    ):
        status = "needs_review"
    if disc is not None and disc >= ANOMALY_DROP_RATIO:
        status = "needs_review"

    if baseline.median is None:
        grade = "이력없음"
        if status == "needs_review":
            grade = "확인필요"
        return ScoreResult(grade, "no_history" if status == "ok" else status, 0, disc, False)

    grade = "확인필요" if status == "needs_review" else grade_from_discount(disc)
    score = 0.0
    if disc is not None:
        score = disc * 100
    if baseline.minimum is not None and offer.price is not None:
        if offer.price <= baseline.minimum:
            score += 8
            if grade == "일반":
                grade = "관심"
    if source_count >= 2:
        score += 5
    if votes:
        score += min(votes, 20) * 0.2

    if last_scored_at:
        if last_scored_at.tzinfo is None:
            last_scored_at = last_scored_at.replace(tzinfo=timezone.utc)
        in_cooldown = now - last_scored_at < timedelta(hours=COOLDOWN_HOURS)
        cheaper = (
            offer.price is not None
            and last_scored_price is not None
            and offer.price < last_scored_price
        )
        if in_cooldown and not cheaper:
            suppress = True

    return ScoreResult(grade, status, round(score, 2), disc, suppress)
