from __future__ import annotations

import logging
import re
import time
from collections import defaultdict

from app.config import SOLDOUT_REPORT_THRESHOLD
from app.db import utcnow_iso
from app.engine.auth import hash_password, verify_password

log = logging.getLogger("hotdeal.comments")

MAX_BODY = 300
MAX_NICK = 12
MAX_PIN_LEN = 4
MIN_BODY = 2
REACTION_KINDS = ("like", "meh", "bought", "soldout")
REPORT_REASONS = (
    "price",
    "link",
    "spam",
    "soldout",
    "illegal",
    "other",
)
BANNED_WORDS = (
    "카지노",
    "바카라",
    "대출상담",
    "성인사이트",
    "텔레그램@",
)
URL_RE = re.compile(r"https?://|www\.", re.I)
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_rate_hits: dict[str, list[float]] = defaultdict(list)


class CommentError(ValueError):
    pass


def _clean_text(raw: str, *, max_len: int) -> str:
    text = CTRL_RE.sub("", (raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = " ".join(text.split(" "))
    return text.strip()[:max_len]


def normalize_nickname(raw: str | None) -> str:
    nick = re.sub(r"\s+", " ", (raw or "").strip())
    nick = nick[:MAX_NICK]
    return nick or "익명"


def normalize_body(raw: str) -> str:
    body = _clean_text(raw, max_len=MAX_BODY)
    if len(body) < MIN_BODY:
        raise CommentError("댓글을 조금 더 적어 주세요")
    return body


def normalize_pin(raw: str | None) -> str:
    pin = re.sub(r"\D", "", raw or "")
    if len(pin) != MAX_PIN_LEN:
        raise CommentError("숫자 4자리 PIN이 필요합니다")
    return pin


def check_rate(client_key: str, ip: str) -> None:
    now = time.time()
    for key, window, limit in (
        (f"c10:{client_key}", 10, 1),
        (f"c300:{client_key}", 300, 5),
        (f"ip300:{ip or 'unknown'}", 300, 20),
    ):
        hits = [t for t in _rate_hits[key] if now - t < window]
        if len(hits) >= limit:
            raise CommentError("잠시 후 다시 남겨 주세요")
        hits.append(now)
        _rate_hits[key] = hits[-40:]


def _url_count(text: str) -> int:
    return len(URL_RE.findall(text or ""))


def _has_banned(text: str) -> bool:
    hay = (text or "").lower()
    return any(word.lower() in hay for word in BANNED_WORDS)


def public_comment(row: dict, *, mine: bool = False, admin: bool = False) -> dict:
    deleted = bool(row.get("deleted_at"))
    return {
        "id": int(row["id"]),
        "deal_id": int(row["deal_id"]),
        "parent_id": int(row["parent_id"]) if row.get("parent_id") else None,
        "nickname": row.get("nickname") or "익명",
        "body": "삭제된 댓글입니다" if deleted else row.get("body") or "",
        "created_at": row.get("created_at"),
        "deleted": deleted,
        "mine": mine,
        "can_delete": (not deleted) and (mine or admin),
        "parent_nickname": row.get("parent_nickname") or None,
        "parent_body": row.get("parent_body") or None,
    }


async def comment_counts(conn, deal_ids: list[int]) -> dict[int, int]:
    if not deal_ids:
        return {}
    placeholders = ",".join("?" for _ in deal_ids)
    cur = await conn.execute(
        f"""
        SELECT deal_id, COUNT(*) AS c
        FROM deal_comments
        WHERE deal_id IN ({placeholders}) AND deleted_at IS NULL
        GROUP BY deal_id
        """,
        deal_ids,
    )
    return {int(r["deal_id"]): int(r["c"]) for r in await cur.fetchall()}


async def list_comments(conn, deal_id: int, after_id: int = 0) -> list[dict]:
    cur = await conn.execute(
        """
        SELECT c.*,
               p.nickname AS parent_nickname,
               CASE WHEN p.deleted_at IS NULL THEN p.body ELSE NULL END AS parent_body
        FROM deal_comments c
        LEFT JOIN deal_comments p ON p.id = c.parent_id
        WHERE c.deal_id=? AND c.id > ?
        ORDER BY c.id ASC
        LIMIT 200
        """,
        (deal_id, after_id),
    )
    return [dict(r) for r in await cur.fetchall()]


async def list_user_comments(conn, user_id: int, limit: int = 50) -> list[dict]:
    cur = await conn.execute(
        """
        SELECT c.id, c.deal_id, c.body, c.created_at,
               d.product_name
        FROM deal_comments c
        JOIN deals d ON d.id = c.deal_id
        WHERE c.user_id=? AND c.deleted_at IS NULL
        ORDER BY c.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    return [dict(r) for r in await cur.fetchall()]


async def add_comment(
    conn,
    *,
    deal_id: int,
    nickname: str | None,
    pin: str | None,
    body: str,
    parent_id: int | None,
    client_key: str,
    user: dict | None,
    ip: str,
) -> dict:
    check_rate(client_key, ip)
    nick = normalize_nickname(nickname or (user or {}).get("display_name"))
    text = normalize_body(body)
    pin_norm = normalize_pin(pin)
    if _has_banned(text) or _has_banned(nick):
        raise CommentError("등록할 수 없는 내용입니다")
    urls = _url_count(text)
    if urls >= 2:
        raise CommentError("링크는 한 개만 넣을 수 있습니다")
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM deal_comments WHERE client_key=? AND deleted_at IS NULL",
        (client_key,),
    )
    prior = int((await cur.fetchone())["c"])
    if prior == 0 and urls:
        raise CommentError("첫 댓글에는 링크를 넣을 수 없습니다")
    cur = await conn.execute(
        """
        SELECT body FROM deal_comments
        WHERE deal_id=? AND client_key=? AND deleted_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (deal_id, client_key),
    )
    last = await cur.fetchone()
    if last and (last["body"] or "") == text:
        raise CommentError("같은 내용을 연속으로 남길 수 없습니다")
    parent = None
    if parent_id:
        cur = await conn.execute(
            "SELECT * FROM deal_comments WHERE id=? AND deal_id=?",
            (int(parent_id), deal_id),
        )
        parent = await cur.fetchone()
        if not parent:
            raise CommentError("답글 대상을 찾지 못했습니다")
    now = utcnow_iso()
    user_id = int(user["id"]) if user and user.get("id") else None
    await conn.execute(
        """
        INSERT INTO deal_comments(
            deal_id, parent_id, user_id, nickname, pin_hash, client_key, body, created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            deal_id,
            int(parent["id"]) if parent else None,
            user_id,
            nick,
            hash_password(pin_norm),
            client_key,
            text,
            now,
        ),
    )
    await conn.commit()
    cur = await conn.execute(
        """
        SELECT c.*,
               p.nickname AS parent_nickname,
               CASE WHEN p.deleted_at IS NULL THEN p.body ELSE NULL END AS parent_body
        FROM deal_comments c
        LEFT JOIN deal_comments p ON p.id = c.parent_id
        WHERE c.id = last_insert_rowid()
        """
    )
    row = dict(await cur.fetchone())
    return public_comment(row, mine=True)


async def delete_comment(
    conn,
    comment_id: int,
    *,
    pin: str | None,
    client_key: str | None,
    is_admin: bool,
) -> None:
    cur = await conn.execute("SELECT * FROM deal_comments WHERE id=?", (comment_id,))
    row = await cur.fetchone()
    if not row:
        raise CommentError("댓글을 찾지 못했습니다")
    if row["deleted_at"]:
        return
    allowed = is_admin
    if not allowed and client_key and row["client_key"] == client_key:
        if pin and verify_password(normalize_pin(pin), row["pin_hash"]):
            allowed = True
    if not allowed:
        raise CommentError("삭제할 수 없습니다")
    await conn.execute(
        "UPDATE deal_comments SET deleted_at=? WHERE id=?",
        (utcnow_iso(), comment_id),
    )
    await conn.commit()


async def reaction_snapshot(conn, deal_id: int, client_key: str | None) -> dict:
    cur = await conn.execute(
        """
        SELECT kind, COUNT(*) AS c
        FROM deal_reactions
        WHERE deal_id=?
        GROUP BY kind
        """,
        (deal_id,),
    )
    counts = {k: 0 for k in REACTION_KINDS}
    for row in await cur.fetchall():
        if row["kind"] in counts:
            counts[row["kind"]] = int(row["c"])
    mine: list[str] = []
    if client_key:
        cur = await conn.execute(
            "SELECT kind FROM deal_reactions WHERE deal_id=? AND client_key=?",
            (deal_id, client_key),
        )
        mine = [r["kind"] for r in await cur.fetchall() if r["kind"] in REACTION_KINDS]
    cur = await conn.execute("SELECT status FROM deals WHERE id=?", (deal_id,))
    deal = await cur.fetchone()
    return {
        "counts": counts,
        "mine": mine,
        "expired": bool(deal and (deal["status"] or "") == "expired"),
    }


async def toggle_reaction(conn, *, deal_id: int, client_key: str, kind: str) -> dict:
    if kind not in REACTION_KINDS:
        raise CommentError("지원하지 않는 반응입니다")
    cur = await conn.execute(
        "SELECT 1 FROM deal_reactions WHERE deal_id=? AND client_key=? AND kind=?",
        (deal_id, client_key, kind),
    )
    exists = await cur.fetchone()
    now = utcnow_iso()
    if exists:
        await conn.execute(
            "DELETE FROM deal_reactions WHERE deal_id=? AND client_key=? AND kind=?",
            (deal_id, client_key, kind),
        )
    else:
        await conn.execute(
            "INSERT INTO deal_reactions(deal_id, client_key, kind, created_at) VALUES(?,?,?,?)",
            (deal_id, client_key, kind, now),
        )
    if kind == "soldout":
        await _maybe_expire(conn, deal_id)
    await conn.commit()
    return await reaction_snapshot(conn, deal_id, client_key)


async def _maybe_expire(conn, deal_id: int) -> None:
    cur = await conn.execute(
        """
        SELECT COUNT(DISTINCT client_key) AS c
        FROM deal_reactions
        WHERE deal_id=? AND kind='soldout'
        """,
        (deal_id,),
    )
    count = int((await cur.fetchone())["c"])
    if count >= max(1, SOLDOUT_REPORT_THRESHOLD):
        await conn.execute(
            "UPDATE deals SET status='expired' WHERE id=?",
            (deal_id,),
        )


async def add_report(
    conn,
    *,
    deal_id: int,
    reason: str,
    detail: str | None,
    client_key: str,
) -> None:
    if reason not in REPORT_REASONS:
        raise CommentError("신고 항목을 선택해 주세요")
    text = _clean_text(detail or "", max_len=2000)
    if reason == "other" and len(text) < 4:
        raise CommentError("기타 항목은 내용을 입력해 주세요")
    await conn.execute(
        """
        INSERT INTO deal_reports(deal_id, reason, detail, client_key, created_at)
        VALUES(?,?,?,?,?)
        """,
        (deal_id, reason, text or None, client_key, utcnow_iso()),
    )
    await conn.commit()


async def list_reports(conn, limit: int = 100) -> list[dict]:
    cur = await conn.execute(
        """
        SELECT r.*, d.product_name
        FROM deal_reports r
        LEFT JOIN deals d ON d.id = r.deal_id
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(r) for r in await cur.fetchall()]
