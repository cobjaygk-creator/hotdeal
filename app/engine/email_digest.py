"""Daily "오늘의 초특가" email digest.

Dormant until SMTP_HOST / SMTP_FROM are configured (EMAIL_DIGEST_ENABLED).
Sending goes through stdlib smtplib in a worker thread (no new dependency).
Real delivery can only be verified once real SMTP credentials exist.
"""
from __future__ import annotations

import asyncio
import html
import logging
import smtplib
from email.message import EmailMessage

from app.config import (
    EMAIL_DIGEST_ENABLED,
    SITE_URL,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_STARTTLS,
    SMTP_USER,
)
from app.db import get_meta, set_meta, utcnow_iso

log = logging.getLogger("hotdeal.digest")

MAX_ITEMS = 15


async def _top_deals_today(conn) -> list[dict]:
    cur = await conn.execute(
        """
        SELECT id, product_name, seller, price, discount_rate, grade, mall_url, deal_url
        FROM deals
        WHERE date(last_seen_at, '+9 hours') = date('now', '+9 hours')
          AND (grade LIKE '%초특가%' OR grade LIKE '%특가%')
        ORDER BY score DESC, last_seen_at DESC
        LIMIT ?
        """,
        (MAX_ITEMS,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def digest_recipients(conn) -> list[str]:
    cur = await conn.execute(
        "SELECT email FROM users WHERE digest_opt_in = 1 AND email IS NOT NULL AND TRIM(email) != ''"
    )
    return [r["email"].strip() for r in await cur.fetchall() if r["email"]]


def _won(n) -> str:
    try:
        return f"{int(n):,}원"
    except (TypeError, ValueError):
        return "가격 미확인"


def build_digest(items: list[dict]) -> tuple[str, str, str]:
    subject = f"[핫딜모음] 오늘의 초특가 {len(items)}건"
    lines_txt = ["오늘 올라온 초특가·특가 딜입니다.", ""]
    rows_html = []
    for d in items:
        name = (d.get("product_name") or "핫딜").strip()
        seller = d.get("seller") or "판매처 미상"
        price = _won(d.get("price"))
        link = f"{SITE_URL}/deal/{d.get('id')}"
        lines_txt.append(f"- {name} / {seller} / {price}\n  {link}")
        rows_html.append(
            f'<tr><td style="padding:8px 0;border-bottom:1px solid #eee">'
            f'<a href="{html.escape(link)}" style="color:#5c0282;text-decoration:none;font-weight:600">{html.escape(name)}</a><br>'
            f'<span style="color:#666;font-size:13px">{html.escape(seller)} · {html.escape(price)}</span></td></tr>'
        )
    text = "\n".join(lines_txt) + f"\n\n전체 보기: {SITE_URL}/\n수신 거부는 마이페이지에서."
    body_html = (
        '<div style="font-family:sans-serif;max-width:560px;margin:0 auto">'
        '<h2 style="color:#16181d">오늘의 초특가</h2>'
        '<table style="width:100%;border-collapse:collapse">' + "".join(rows_html) + "</table>"
        f'<p style="margin-top:16px"><a href="{SITE_URL}/">전체 딜 보기</a></p>'
        '<p style="color:#8b94a3;font-size:12px">수신 거부는 마이페이지 &gt; 키워드 알림에서 설정할 수 있습니다.</p>'
        "</div>"
    )
    return subject, body_html, text


def _send_sync(to_addr: str, subject: str, body_html: str, text: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        if SMTP_STARTTLS:
            s.starttls()
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)


async def send_email(to_addr: str, subject: str, body_html: str, text: str) -> bool:
    if not EMAIL_DIGEST_ENABLED:
        return False
    try:
        await asyncio.to_thread(_send_sync, to_addr, subject, body_html, text)
        return True
    except Exception:
        log.exception("digest send failed to=%s", to_addr)
        return False


async def run_digest(conn, *, force: bool = False) -> dict:
    if not EMAIL_DIGEST_ENABLED:
        return {"skipped": "not configured"}
    today = utcnow_iso()[:10]
    if not force and (await get_meta(conn, "last_email_digest_day")) == today:
        return {"skipped": "already sent today"}
    items = await _top_deals_today(conn)
    if not items:
        return {"skipped": "no deals"}
    recipients = await digest_recipients(conn)
    subject, body_html, text = build_digest(items)
    sent = 0
    for addr in recipients:
        if await send_email(addr, subject, body_html, text):
            sent += 1
    await set_meta(conn, "last_email_digest_day", today)
    await set_meta(conn, "last_email_digest_at", utcnow_iso())
    return {"items": len(items), "recipients": len(recipients), "sent": sent}
