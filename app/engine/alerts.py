from __future__ import annotations

import logging

from app.config import (
    ALERT_KEYWORDS,
    ALERT_MIN_GRADE,
    DISCORD_WEBHOOK_URL,
    SITE_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from app.db import utcnow_iso

log = logging.getLogger("hotdeal.alerts")

GRADE_ORDER = ("일반", "관심", "핫딜", "특가", "초특가")
CHANNELS = ("telegram", "discord")


def grade_rank(grade: str | None) -> int:
    text = grade or ""
    if "초특가" in text:
        return 4
    if "특가" in text:
        return 3
    if "핫딜" in text:
        return 2
    if "관심" in text:
        return 1
    if text == "일반":
        return 0
    return -1


def meets_min_grade(grade: str | None, min_grade: str | None) -> bool:
    return grade_rank(grade) >= grade_rank(min_grade or "핫딜")


def keyword_tokens(keyword: str) -> list[str]:
    return [t for t in (keyword or "").casefold().split() if t]


def matches_keyword(deal: dict, keyword: str) -> bool:
    tokens = keyword_tokens(keyword)
    if not tokens:
        return False
    hay = f"{deal.get('product_name') or ''} {deal.get('seller') or ''}".casefold()
    return all(t in hay for t in tokens)


def format_alert(deal: dict, keyword: str) -> str:
    price = deal.get("price")
    price_txt = f"{int(price):,}원" if price else "가격 미확인"
    disc = deal.get("discount_rate")
    drop = f" ({-disc * 100:.1f}%)" if disc is not None else ""
    grade = deal.get("grade") or ""
    name = (deal.get("product_name") or "핫딜").strip()
    seller = deal.get("seller") or "판매처 미상"
    url = f"{SITE_URL}/deal/{deal.get('id')}"
    mall = deal.get("mall_url") or ""
    lines = [
        f"{grade} · {name}" if grade else name,
        f"{seller} · {price_txt}{drop}",
        f"키워드: {keyword}",
        url,
    ]
    if mall:
        lines.append(f"구매: {mall}")
    return "\n".join(lines)


async def seed_env_subs(conn) -> None:
    keywords = [k.strip() for k in ALERT_KEYWORDS.split(",") if k.strip()]
    if not keywords:
        return
    now = utcnow_iso()
    targets = []
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        targets.append(("telegram", TELEGRAM_CHAT_ID))
    if DISCORD_WEBHOOK_URL:
        targets.append(("discord", DISCORD_WEBHOOK_URL))
    for keyword in keywords:
        for channel, target in targets:
            await conn.execute(
                """
                INSERT INTO alert_subs(keyword, min_grade, channel, target, enabled, origin, created_at)
                VALUES(?, ?, ?, ?, 1, 'env', ?)
                ON CONFLICT(keyword, channel, target) DO UPDATE SET
                    min_grade=excluded.min_grade,
                    enabled=1,
                    origin='env'
                """,
                (keyword, ALERT_MIN_GRADE, channel, target, now),
            )


async def list_subs(conn, *, include_user: bool = False) -> list[dict]:
    if include_user:
        cur = await conn.execute(
            "SELECT * FROM alert_subs ORDER BY enabled DESC, id DESC"
        )
    else:
        cur = await conn.execute(
            """
            SELECT * FROM alert_subs
            WHERE COALESCE(origin, 'admin') != 'user'
            ORDER BY enabled DESC, id DESC
            """
        )
    return [dict(r) for r in await cur.fetchall()]


async def add_sub(conn, *, keyword: str, min_grade: str, channel: str, target: str) -> None:
    keyword = keyword.strip()
    channel = channel.strip().lower()
    target = target.strip()
    if not keyword or channel not in CHANNELS or not target:
        raise ValueError("keyword, channel, target required")
    min_grade = min_grade.strip() or "핫딜"
    await conn.execute(
        """
        INSERT INTO alert_subs(keyword, min_grade, channel, target, enabled, origin, created_at)
        VALUES(?, ?, ?, ?, 1, 'admin', ?)
        ON CONFLICT(keyword, channel, target) DO UPDATE SET
            min_grade=excluded.min_grade,
            enabled=1
        """,
        (keyword, min_grade, channel, target, utcnow_iso()),
    )


async def delete_sub(conn, sub_id: int) -> None:
    await conn.execute("DELETE FROM alert_sent WHERE sub_id=?", (sub_id,))
    await conn.execute("DELETE FROM alert_subs WHERE id=?", (sub_id,))


async def delete_user_subs(conn, user_id: int) -> None:
    cur = await conn.execute("SELECT id FROM alert_subs WHERE user_id=?", (user_id,))
    ids = [int(r["id"]) for r in await cur.fetchall()]
    for sub_id in ids:
        await conn.execute("DELETE FROM alert_sent WHERE sub_id=?", (sub_id,))
    await conn.execute("DELETE FROM alert_subs WHERE user_id=?", (user_id,))


async def add_user_sub(
    conn,
    *,
    user_id: int,
    keyword: str,
    min_grade: str,
    channel: str,
    target: str,
) -> None:
    keyword = keyword.strip()
    channel = channel.strip().lower()
    target = target.strip()
    if not keyword or channel not in CHANNELS or not target:
        return
    await conn.execute(
        """
        INSERT INTO alert_subs(keyword, min_grade, channel, target, enabled, origin, created_at, user_id)
        VALUES(?, ?, ?, ?, 1, 'user', ?, ?)
        ON CONFLICT(keyword, channel, target) DO UPDATE SET
            min_grade=excluded.min_grade,
            enabled=1,
            origin='user',
            user_id=excluded.user_id
        """,
        (keyword, min_grade.strip() or "핫딜", channel, target, utcnow_iso(), user_id),
    )


def default_target(channel: str) -> str:
    if channel == "telegram":
        return TELEGRAM_CHAT_ID
    if channel == "discord":
        return DISCORD_WEBHOOK_URL
    return ""


def channels_ready() -> dict[str, bool]:
    return {
        "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "discord": bool(DISCORD_WEBHOOK_URL),
    }


async def dispatch_alerts(conn, client, deals: list[dict]) -> dict:
    summary = {"checked": 0, "sent": 0, "skipped": 0, "errors": 0}
    if not deals:
        return summary
    cur = await conn.execute("SELECT * FROM alert_subs WHERE enabled=1")
    subs = [dict(r) for r in await cur.fetchall()]
    if not subs:
        return summary
    seen_ids: set[int] = set()
    for deal in deals:
        did = deal.get("id")
        if not did or did in seen_ids:
            continue
        seen_ids.add(did)
        summary["checked"] += 1
        for sub in subs:
            if not matches_keyword(deal, sub["keyword"]):
                continue
            if not meets_min_grade(deal.get("grade"), sub.get("min_grade")):
                summary["skipped"] += 1
                continue
            sent = await conn.execute(
                "SELECT 1 FROM alert_sent WHERE sub_id=? AND deal_id=?",
                (sub["id"], did),
            )
            if await sent.fetchone():
                summary["skipped"] += 1
                continue
            try:
                await _deliver(client, sub, deal)
            except Exception:
                log.exception("alert send failed sub=%s deal=%s", sub["id"], did)
                summary["errors"] += 1
                continue
            await conn.execute(
                "INSERT OR IGNORE INTO alert_sent(sub_id, deal_id, sent_at) VALUES(?,?,?)",
                (sub["id"], did, utcnow_iso()),
            )
            summary["sent"] += 1
    return summary


async def _deliver(client, sub: dict, deal: dict) -> None:
    text = format_alert(deal, sub["keyword"])
    channel = sub["channel"]
    target = sub["target"]
    if channel == "telegram":
        if not TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": target, "text": text, "disable_web_page_preview": False}
        await client.post_json(url, payload)
        return
    if channel == "discord":
        await client.post_json(target, {"content": text[:1900]})
        return
    raise RuntimeError(f"unknown channel {channel}")
