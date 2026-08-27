from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import BASELINE_DAYS, MIN_BASELINE_SAMPLES


@dataclass
class Baseline:
    median: int | None
    minimum: int | None
    sample_count: int
    points: list[tuple[datetime, int]]


def compute_baseline(
    prices: list[tuple[datetime | str, int]],
    now: datetime | None = None,
    days: int = BASELINE_DAYS,
    min_samples: int = MIN_BASELINE_SAMPLES,
) -> Baseline:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    cleaned: list[tuple[datetime, int]] = []
    for observed, price in prices:
        dt = _as_dt(observed)
        if dt is None or price is None or price <= 0:
            continue
        if dt >= cutoff:
            cleaned.append((dt, int(price)))
    cleaned.sort(key=lambda x: x[0])
    values = [p for _, p in cleaned]
    if len(values) < min_samples:
        return Baseline(None, min(values) if values else None, len(values), cleaned)
    return Baseline(
        median=int(statistics.median(values)),
        minimum=min(values),
        sample_count=len(values),
        points=cleaned,
    )


def discount_rate(current: int | None, baseline: int | None) -> float | None:
    if not current or not baseline or baseline <= 0:
        return None
    return (baseline - current) / baseline


def _as_dt(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
