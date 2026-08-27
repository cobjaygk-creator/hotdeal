from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def parse_int(text: str | None) -> int:
    if not text:
        return 0
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def parse_kr_datetime(value: str | None, now: datetime | None = None) -> datetime | None:
    """Parse '26.08.27 13:51:09', '26/08/26', '13:51:09', '3분 전'."""
    if not value:
        return None
    text = value.strip()
    now = now or datetime.now(KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)

    relative = _relative(text, now)
    if relative:
        return relative

    text = text.replace(".", "-").replace("/", "-")
    for fmt in ("%y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%y-%m-%d", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=KST)
            return dt
        except ValueError:
            continue
    try:
        md = datetime.strptime(text, "%m-%d")
        return now.replace(month=md.month, day=md.day, hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        pass
    if ":" in text and len(text) <= 8:
        try:
            t = datetime.strptime(text, "%H:%M:%S" if text.count(":") == 2 else "%H:%M")
            return now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
        except ValueError:
            return None
    return None


def _relative(text: str, now: datetime) -> datetime | None:
    import re

    m = re.fullmatch(r"(\d+)\s*분\s*전", text)
    if m:
        from datetime import timedelta

        return now - timedelta(minutes=int(m.group(1)))
    m = re.fullmatch(r"(\d+)\s*시간\s*전", text)
    if m:
        from datetime import timedelta

        return now - timedelta(hours=int(m.group(1)))
    m = re.fullmatch(r"(\d+)\s*일\s*전", text)
    if m:
        from datetime import timedelta

        return now - timedelta(days=int(m.group(1)))
    m = re.fullmatch(r"(\d+)\s*초\s*전", text)
    if m:
        return now
    return None


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def format_kst(value: str | None) -> str:
    """Render stored UTC timestamps as Korea time."""
    if not value:
        return "-"
    raw = str(value).strip()
    try:
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return raw
