"""Moyo (moyoplan.com) event-plan scraper.

The /plans/themes/one-month-free page server-renders a `planMeta` JSON object
per plan into its RSC stream, so a plain fetch is enough — no headless
browser. We keep only plans that carry a promo (benefits.giftGroupList):
those are the genuinely event/limited "혜택가 0원" plans.
"""
from __future__ import annotations

import json
import re

from app.http_client import PoliteClient

# Add more SSR'd theme URLs here (comma-separated env override lives in config).
DEFAULT_THEME_URLS = (
    "https://www.moyoplan.com/plans/themes/one-month-free",
)

_PLANMETA_RE = re.compile(r'"planMeta"\s*:')


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def _iter_plan_json(html: str):
    s = _unescape(html or "")
    for m in _PLANMETA_RE.finditer(s):
        try:
            start = s.index("{", m.end())
        except ValueError:
            continue
        depth = 0
        for j in range(start, min(start + 12000, len(s))):
            c = s[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        yield json.loads(s[start : j + 1])
                    except json.JSONDecodeError:
                        pass
                    break


def _fee(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and v >= 0 else None


def _to_row(p: dict) -> dict | None:
    pid = p.get("id")
    if not isinstance(pid, int):
        return None
    gifts = ((p.get("benefits") or {}).get("giftGroupList")) or []
    if not gifts:  # not an event plan
        return None
    op = p.get("operator") or {}
    spec = p.get("specifications") or {}
    data = spec.get("data") or {}
    pr = p.get("pricing") or {}
    disc_period = pr.get("discountPeriod")
    voice = spec.get("voice")
    return {
        "plan_id": pid,
        "name": (p.get("name") or "").strip(),
        "mvno": (op.get("brandName") or "").strip() or None,
        "mno": (op.get("mno") or "").strip() or None,
        "network": (op.get("network") or "").strip() or None,
        "data_gb": None if data.get("isUnlimited") else data.get("monthly"),
        "data_unlimited": 1 if data.get("isUnlimited") else 0,
        "data_daily_gb": data.get("daily") or None,
        "qos_kbps": data.get("qos") or None,
        "voice_min": voice if (isinstance(voice, int) and voice >= 0) else None,
        "voice_unlimited": 1 if spec.get("isVoiceUnlimited") else 0,
        "sms_unlimited": 1 if spec.get("isMessageUnlimited") else 0,
        "original_fee": _fee(pr.get("originalFee")),
        "discount_fee": _fee(pr.get("discountFee")),
        "discount_months": disc_period if isinstance(disc_period, int) else None,
        "promo": (gifts[0].get("title") or "").strip() or None,
        "promo_all": json.dumps(
            [g.get("title") for g in gifts if g.get("title")], ensure_ascii=False
        ),
        "rating": (p.get("statistics") or {}).get("rating"),
        "signup_count": (p.get("statistics") or {}).get("signup1MonthCount"),
        "plan_url": f"https://www.moyoplan.com/plans/{pid}",
        "brand_image": (op.get("brandImageUrl") or "").strip() or None,
    }


def parse_plans(html: str) -> list[dict]:
    out: list[dict] = []
    seen: set[int] = set()
    for p in _iter_plan_json(html):
        row = _to_row(p)
        if not row or row["plan_id"] in seen or not row["name"]:
            continue
        seen.add(row["plan_id"])
        out.append(row)
    return out


async def fetch_plans(client: PoliteClient, theme_urls: tuple[str, ...] | None = None) -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    for url in theme_urls or DEFAULT_THEME_URLS:
        try:
            result = await client.get(url, timeout=15.0, max_retries=2)
        except Exception:  # noqa: BLE001
            continue
        if result.not_modified or not result.text:
            continue
        for row in parse_plans(result.text):
            if row["plan_id"] in seen:
                continue
            seen.add(row["plan_id"])
            rows.append(row)
    return rows
