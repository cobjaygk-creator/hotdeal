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
CHANNELS = ("telegram", "discord", "webpush")
# Channels that need a per-user target string (chat id / webhook url).
TARGET_CHANNELS = ("telegram", "discord")


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


def matches_keyword(deal: dict, keyword: str, exclude_keywords: str = '') -> bool:
    tokens = keyword_tokens(keyword)
    if not tokens:
        return False
    hay = f"{deal.get('product_name') or ''} {deal.get('seller') or ''}".casefold()
    if not all(t in hay for t in tokens):
        return False
    excluded = keyword_tokens(exclude_keywords.replace(',', ' '))
    return not any(t in hay for t in excluded)


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


async def reconcile_user_subs(
    conn, *, user_id: int, keywords: list[tuple[str, str, str, int]], channel: str, target: str
) -> None:
    """Bring a user's alert_subs in line with their keyword list + notify
    setting WITHOUT churning rows for unchanged (keyword, channel, target)
    tuples — so alert_sent (which doubles as the in-app inbox) survives a
    keyword add/remove."""
    channel = (channel or "").strip().lower()
    target = (target or "").strip()
    if channel not in CHANNELS:
        channel = ""
    if channel in TARGET_CHANNELS and not target:
        channel, target = "", ""  # unusable target -> inbox-only
    eff_target = target if channel in TARGET_CHANNELS else f"u{user_id}"
    desired: dict[tuple[str, str, str], str] = {}
    for kw, grade, excluded, enabled in keywords:
        kw = (kw or "").strip()
        if kw:
            desired[(kw, channel, eff_target)] = ((grade or "핫딜").strip() or "핫딜", excluded or "", 1 if enabled else 0)

    cur = await conn.execute(
        "SELECT id, keyword, channel, target FROM alert_subs WHERE user_id=?",
        (user_id,),
    )
    for r in await cur.fetchall():
        if (r["keyword"], r["channel"] or "", r["target"] or "") not in desired:
            await conn.execute("DELETE FROM alert_sent WHERE sub_id=?", (r["id"],))
            await conn.execute("DELETE FROM alert_subs WHERE id=?", (r["id"],))

    now = utcnow_iso()
    for (kw, ch, tg), grade in desired.items():
        await conn.execute(
            """
            INSERT INTO alert_subs(keyword, min_grade, channel, target, exclude_keywords, enabled, origin, created_at, user_id)
            VALUES(?, ?, ?, ?, ?, ?, 'user', ?, ?)
            ON CONFLICT(keyword, channel, target) DO UPDATE SET
                min_grade=excluded.min_grade, exclude_keywords=excluded.exclude_keywords, enabled=excluded.enabled, origin='user', user_id=excluded.user_id
            """,
            (kw, grade[0], ch, tg, grade[1], grade[2], now, user_id),
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
    sent_user_deals: set[tuple[int, int]] = set()
    for deal in deals:
        did = deal.get("id")
        if not did or did in seen_ids:
            continue
        seen_ids.add(did)
        summary["checked"] += 1
        for sub in subs:
            if not matches_keyword(deal, sub["keyword"], sub.get("exclude_keywords") or ''):
                continue
            if not meets_min_grade(deal.get("grade"), sub.get("min_grade")):
                summary["skipped"] += 1
                continue
            user_id = sub.get("user_id")
            if user_id and (int(user_id), int(did)) in sent_user_deals:
                summary["skipped"] += 1
                continue
            sent = await conn.execute(
                "SELECT 1 FROM alert_sent WHERE sub_id=? AND deal_id=?",
                (sub["id"], did),
            )
            if await sent.fetchone():
                summary["skipped"] += 1
                continue
            # Record it first so the in-app inbox shows every match even if
            # the outbound channel (telegram/discord/webpush) fails.
            await conn.execute(
                "INSERT OR IGNORE INTO alert_sent(sub_id, deal_id, sent_at) VALUES(?,?,?)",
                (sub["id"], did, utcnow_iso()),
            )
            if user_id:
                sent_user_deals.add((int(user_id), int(did)))
            if not sub.get("channel"):
                summary["sent"] += 1
                continue
            # 조용히 모드: 사용자 quiet_start~quiet_end 범위면 외부 발송 스킵
            if user_id and await _is_quiet_hour(conn, int(user_id)):
                summary["skipped"] += 1
                continue
            try:
                await _deliver(conn, client, sub, deal)
                summary["sent"] += 1
            except Exception:
                log.exception("alert send failed sub=%s deal=%s", sub["id"], did)
                summary["errors"] += 1
                # Drop the marker so a transient failure retries next cycle.
                # (The inbox entry is re-created then too.)
                await conn.execute(
                    "DELETE FROM alert_sent WHERE sub_id=? AND deal_id=?",
                    (sub["id"], did),
                )
    return summary


async def _deliver(conn, client, sub: dict, deal: dict) -> None:
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
    if channel == "webpush":
        await _deliver_webpush(conn, sub, deal)
        return
    raise RuntimeError(f"unknown channel {channel}")


async def _deliver_webpush(conn, sub: dict, deal: dict) -> None:
    from app.engine.push import send_web_push

    user_id = sub.get("user_id")
    if not user_id:
        return
    cur = await conn.execute(
        "SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id=?",
        (user_id,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows:
        return
    payload = {
        "title": (deal.get("product_name") or "핫딜").strip(),
        "body": format_alert(deal, sub["keyword"]).split("\n", 1)[-1][:180],
        "url": f"{SITE_URL}/deal/{deal.get('id')}",
    }
    for row in rows:
        info = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        status = await send_web_push(info, payload)
        if status in (404, 410):
            await conn.execute(
                "DELETE FROM push_subscriptions WHERE id=?", (row["id"],)
            )


def _family_alert_text(sale: dict, notif_type: str) -> str:
    """패밀리세일 알림 텍스트 생성 (D-1 / D-0 공용)."""
    import json as _json
    title = sale.get("title") or ""
    brands = sale.get("brand_names") or ""
    try:
        brands_list = _json.loads(brands) if isinstance(brands, str) and brands.startswith("[") else []
        brands_label = " / ".join(brands_list) if brands_list else brands
    except Exception:
        brands_label = brands
    discount = sale.get("discount_label") or sale.get("discount_max")
    disc_txt = f"{discount}%+" if isinstance(discount, int) else (str(discount) if discount else "")
    deal_url = sale.get("deal_url") or sale.get("source_url") or f"{SITE_URL}/family"
    prefix = "🛍️ [내일 시작]" if notif_type == "d1" else "🎉 [오늘 시작]"
    lines = [
        f"{prefix} {title}",
        f"브랜드: {brands_label}" if brands_label else None,
        f"할인: {disc_txt}" if disc_txt else None,
        f"기간: {sale.get('start_date', '')[:10]} ~ {sale.get('end_date', '')[:10]}",
        deal_url,
    ]
    return "\n".join(l for l in lines if l)


async def _deliver_family_alert_to_user(conn, client, user_id: int, text: str) -> bool:
    """사용자 개인 채널로 패밀리세일 알림 발송. 성공하면 True."""
    cur = await conn.execute(
        "SELECT notify_channel, notify_target FROM users WHERE id=?", (user_id,)
    )
    row = await cur.fetchone()
    if not row:
        return False
    channel = row["notify_channel"] or ""
    target = row["notify_target"] or ""
    try:
        if channel == "telegram" and target and TELEGRAM_BOT_TOKEN:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            await client.post_json(url, {"chat_id": target, "text": text})
            return True
        if channel == "discord" and target:
            await client.post_json(target, {"content": text[:1900]})
            return True
        if channel == "webpush":
            from app.engine.push import send_web_push
            cur2 = await conn.execute(
                "SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id=?",
                (user_id,),
            )
            subs = [dict(r) for r in await cur2.fetchall()]
            payload = {"title": text.split("\n", 1)[0], "body": text, "url": f"{SITE_URL}/family"}
            for s in subs:
                info = {"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}
                status = await send_web_push(info, payload)
                if status in (404, 410):
                    await conn.execute("DELETE FROM push_subscriptions WHERE id=?", (s["id"],))
            return bool(subs)
    except Exception:
        log.exception("family user alert failed user=%s channel=%s", user_id, channel)
    return False


async def dispatch_family_d1_alerts(conn, client) -> int:
    """D-1 알림: 내일 시작하는 패밀리세일 — 사이트 채널 + per-user 개별 발송."""
    from datetime import date, timedelta

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    cur = await conn.execute(
        "SELECT fs.* FROM family_sales fs WHERE fs.start_date LIKE ? || '%'",
        (tomorrow,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows:
        return 0

    now = utcnow_iso()
    sent = 0
    for sale in rows:
        text = _family_alert_text(sale, "d1")
        sale_id = sale["id"]

        # ── 사이트 전체 채널 (기존, 중복 방지) ──────────────────────
        site_sent = await conn.execute(
            "SELECT 1 FROM family_notif_sent WHERE sale_id=? AND notif_type='d1'",
            (sale_id,),
        )
        if not await site_sent.fetchone():
            try:
                if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    await client.post_json(url, {"chat_id": TELEGRAM_CHAT_ID, "text": text})
                if DISCORD_WEBHOOK_URL:
                    await client.post_json(DISCORD_WEBHOOK_URL, {"content": text[:1900]})
                await conn.execute(
                    "INSERT OR IGNORE INTO family_notif_sent(sale_id, notif_type, sent_at) VALUES(?,?,?)",
                    (sale_id, "d1", now),
                )
                sent += 1
            except Exception:
                log.exception("family d1 site alert failed sale=%s", sale_id)

        # ── per-user 개별 발송 ───────────────────────────────────────
        # family_sale_wishes에서 notif_d1=1인 사용자 조회
        # 이미 발송한 경우: family_notif_sent에 (sale_id, 'd1_user_{user_id}') 기록
        cur2 = await conn.execute(
            """SELECT fw.user_id FROM family_sale_wishes fw
               WHERE fw.sale_id=? AND fw.notif_d1=1 AND fw.user_id IS NOT NULL""",
            (sale_id,),
        )
        user_rows = [r["user_id"] for r in await cur2.fetchall()]
        for uid in user_rows:
            notif_key = f"d1_u{uid}"
            check = await conn.execute(
                "SELECT 1 FROM family_notif_sent WHERE sale_id=? AND notif_type=?",
                (sale_id, notif_key),
            )
            if await check.fetchone():
                continue
            if await _is_quiet_hour(conn, uid):
                continue
            ok = await _deliver_family_alert_to_user(conn, client, uid, text)
            # 발송 성공/실패 무관하게 중복 방지 기록 (실패시 다음 사이클에서 재시도 안 함)
            await conn.execute(
                "INSERT OR IGNORE INTO family_notif_sent(sale_id, notif_type, sent_at) VALUES(?,?,?)",
                (sale_id, notif_key, now),
            )
            if ok:
                sent += 1

        await conn.commit()
        log.info("family d1 done sale=%s", sale_id)

    return sent


async def dispatch_family_d0_alerts(conn, client) -> int:
    """D-0 알림: 오늘 시작하는 패밀리세일 — notif_d0=1인 사용자에게 개별 발송."""
    from datetime import date

    today = date.today().isoformat()
    cur = await conn.execute(
        "SELECT fs.* FROM family_sales fs WHERE fs.start_date LIKE ? || '%'",
        (today,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows:
        return 0

    now = utcnow_iso()
    sent = 0
    for sale in rows:
        sale_id = sale["id"]
        text = _family_alert_text(sale, "d0")

        cur2 = await conn.execute(
            """SELECT fw.user_id FROM family_sale_wishes fw
               WHERE fw.sale_id=? AND fw.notif_d0=1 AND fw.user_id IS NOT NULL""",
            (sale_id,),
        )
        user_rows = [r["user_id"] for r in await cur2.fetchall()]
        for uid in user_rows:
            notif_key = f"d0_u{uid}"
            check = await conn.execute(
                "SELECT 1 FROM family_notif_sent WHERE sale_id=? AND notif_type=?",
                (sale_id, notif_key),
            )
            if await check.fetchone():
                continue
            if await _is_quiet_hour(conn, uid):
                continue
            ok = await _deliver_family_alert_to_user(conn, client, uid, text)
            await conn.execute(
                "INSERT OR IGNORE INTO family_notif_sent(sale_id, notif_type, sent_at) VALUES(?,?,?)",
                (sale_id, notif_key, now),
            )
            if ok:
                sent += 1

        await conn.commit()

    return sent


async def _is_quiet_hour(conn, user_id: int) -> bool:
    """사용자의 조용히 모드(quiet_start~quiet_end)가 현재 KST 시각에 활성 중이면 True."""
    from datetime import datetime, timezone, timedelta
    cur = await conn.execute(
        "SELECT quiet_start, quiet_end FROM users WHERE id=?", (user_id,)
    )
    row = await cur.fetchone()
    if not row or row["quiet_start"] is None or row["quiet_end"] is None:
        return False
    kst_hour = datetime.now(tz=timezone(timedelta(hours=9))).hour
    s, e = int(row["quiet_start"]), int(row["quiet_end"])
    if s <= e:
        return s <= kst_hour < e
    # 자정을 넘는 경우 (예: 23~7)
    return kst_hour >= s or kst_hour < e
