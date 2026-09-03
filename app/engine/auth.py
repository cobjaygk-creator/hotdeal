from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from hashlib import sha256
from urllib.parse import urlencode

import httpx

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    KAKAO_CLIENT_ID,
    KAKAO_CLIENT_SECRET,
    SESSION_SECRET,
    SITE_URL,
)
from app.db import utcnow_iso
from app.engine.alerts import CHANNELS

log = logging.getLogger("hotdeal.auth")

SESSION_COOKIE = "hd_session"
OAUTH_COOKIE = "hd_oauth"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
PROVIDERS = ("google", "kakao")
MAX_BOOKMARKS = 200
MAX_KEYWORDS = 30
# Used only when ADMIN_PASSWORD env is empty at first admin seed.
_LOCAL_ADMIN_BOOTSTRAP_PASSWORD = "V_NmpnP7T9Unjbhx"
_PBKDF2_ROUNDS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    raw = (password or "").encode("utf-8")
    used_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw, used_salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${used_salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not password:
        return False
    try:
        algo, salt_hex, digest_hex = encoded.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return hmac.compare_digest(digest, expected)


def is_admin_user(user: dict | None) -> bool:
    if not user:
        return False
    try:
        return int(user.get("is_admin") or 0) == 1
    except (TypeError, ValueError):
        return False


async def ensure_local_admin(conn) -> None:
    """Create or refresh the local admin account (username ADMIN_USERNAME)."""
    username = (ADMIN_USERNAME or "admin").strip() or "admin"
    password = (ADMIN_PASSWORD or "").strip() or _LOCAL_ADMIN_BOOTSTRAP_PASSWORD
    now = utcnow_iso()
    cur = await conn.execute(
        "SELECT id, password_hash FROM users WHERE username=? COLLATE NOCASE",
        (username,),
    )
    row = await cur.fetchone()
    pwd_hash = hash_password(password)
    if row:
        # Refresh hash when ADMIN_PASSWORD env is explicitly set.
        if (ADMIN_PASSWORD or "").strip():
            await conn.execute(
                """
                UPDATE users
                SET password_hash=?, is_admin=1, display_name=COALESCE(NULLIF(display_name,''), '관리자'),
                    last_login_at=last_login_at
                WHERE id=?
                """,
                (pwd_hash, int(row["id"])),
            )
            await conn.commit()
        else:
            await conn.execute(
                "UPDATE users SET is_admin=1 WHERE id=? AND IFNULL(is_admin,0)=0",
                (int(row["id"]),),
            )
            await conn.commit()
        return
    await conn.execute(
        """
        INSERT INTO users(display_name, email, username, password_hash, is_admin, created_at, last_login_at)
        VALUES(?, NULL, ?, ?, 1, ?, ?)
        """,
        ("관리자", username, pwd_hash, now, now),
    )
    await conn.commit()
    log.info("local admin user ensured username=%s", username)


async def authenticate_local(conn, username: str, password: str) -> dict | None:
    name = (username or "").strip()
    if not name or not password:
        return None
    cur = await conn.execute(
        "SELECT * FROM users WHERE username=? COLLATE NOCASE",
        (name,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    user = dict(row)
    if not verify_password(password, user.get("password_hash")):
        return None
    await conn.execute(
        "UPDATE users SET last_login_at=? WHERE id=?",
        (utcnow_iso(), int(user["id"])),
    )
    await conn.commit()
    return await get_user(conn, int(user["id"]))


def cookie_secure() -> bool:
    return SITE_URL.startswith("https://")


def providers_ready() -> dict[str, bool]:
    return {
        "google": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "kakao": bool(KAKAO_CLIENT_ID),
    }


def any_provider() -> bool:
    ready = providers_ready()
    return ready["google"] or ready["kakao"]


def sign_user_id(user_id: int) -> str:
    payload = str(int(user_id))
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), sha256).hexdigest()
    return f"{payload}.{sig}"


def read_user_id(token: str | None) -> int | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if not payload.isdigit():
        return None
    return int(payload)


def new_oauth_state(provider: str) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(18)
    return f"{provider}:{nonce}", nonce


def oauth_cookie_ok(cookie: str | None, provider: str, query_state: str | None) -> bool:
    if not cookie or not query_state:
        return False
    expected = f"{provider}:{query_state}"
    return hmac.compare_digest(cookie, expected)


def authorize_url(provider: str, nonce: str) -> str:
    redirect = redirect_uri(provider)
    if provider == "google":
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": GOOGLE_CLIENT_ID,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": "openid email profile",
                "state": nonce,
                "access_type": "online",
                "prompt": "select_account",
            }
        )
    if provider == "kakao":
        return "https://kauth.kakao.com/oauth/authorize?" + urlencode(
            {
                "client_id": KAKAO_CLIENT_ID,
                "redirect_uri": redirect,
                "response_type": "code",
                "state": nonce,
            }
        )
    raise ValueError(provider)


def redirect_uri(provider: str) -> str:
    return f"{SITE_URL}/auth/{provider}/callback"


async def exchange_code(provider: str, code: str) -> dict:
    redirect = redirect_uri(provider)
    async with httpx.AsyncClient(timeout=20.0) as client:
        if provider == "google":
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            access = token_resp.json().get("access_token")
            info = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access}"},
            )
            info.raise_for_status()
            data = info.json()
            return {
                "subject": str(data.get("sub") or ""),
                "email": data.get("email"),
                "display_name": data.get("name") or data.get("email") or "Google 사용자",
            }
        if provider == "kakao":
            form = {
                "grant_type": "authorization_code",
                "client_id": KAKAO_CLIENT_ID,
                "redirect_uri": redirect,
                "code": code,
            }
            if KAKAO_CLIENT_SECRET:
                form["client_secret"] = KAKAO_CLIENT_SECRET
            token_resp = await client.post(
                "https://kauth.kakao.com/oauth/token",
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
            )
            token_resp.raise_for_status()
            access = token_resp.json().get("access_token")
            info = await client.get(
                "https://kapi.kakao.com/v2/user/me",
                headers={"Authorization": f"Bearer {access}"},
            )
            info.raise_for_status()
            data = info.json()
            account = data.get("kakao_account") or {}
            profile = account.get("profile") or data.get("properties") or {}
            name = profile.get("nickname") or "카카오 사용자"
            return {
                "subject": str(data.get("id") or ""),
                "email": account.get("email"),
                "display_name": name,
            }
    raise ValueError(provider)


async def upsert_oauth_user(conn, *, provider: str, profile: dict) -> dict:
    subject = (profile.get("subject") or "").strip()
    if not subject:
        raise ValueError("oauth subject missing")
    now = utcnow_iso()
    name = (profile.get("display_name") or "사용자").strip()[:40]
    email = (profile.get("email") or None)
    cur = await conn.execute(
        "SELECT user_id FROM oauth_identities WHERE provider=? AND subject=?",
        (provider, subject),
    )
    row = await cur.fetchone()
    if row:
        user_id = int(row["user_id"])
        await conn.execute(
            "UPDATE users SET display_name=?, email=COALESCE(?, email), last_login_at=? WHERE id=?",
            (name, email, now, user_id),
        )
    else:
        await conn.execute(
            """
            INSERT INTO users(display_name, email, created_at, last_login_at)
            VALUES(?, ?, ?, ?)
            """,
            (name, email, now, now),
        )
        cur = await conn.execute("SELECT last_insert_rowid() AS id")
        user_id = int((await cur.fetchone())["id"])
        await conn.execute(
            """
            INSERT INTO oauth_identities(provider, subject, user_id, email)
            VALUES(?, ?, ?, ?)
            """,
            (provider, subject, user_id, email),
        )
    await conn.commit()
    user = await get_user(conn, user_id)
    if not user:
        raise RuntimeError("user missing after upsert")
    return user


async def get_user(conn, user_id: int) -> dict | None:
    cur = await conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def user_from_request(request, conn) -> dict | None:
    uid = read_user_id(request.cookies.get(SESSION_COOKIE))
    if not uid:
        return None
    return await get_user(conn, uid)


def public_user(user: dict | None) -> dict | None:
    if not user:
        return None
    return {
        "id": user["id"],
        "display_name": user.get("display_name") or "사용자",
        "username": user.get("username") or "",
        "is_admin": is_admin_user(user),
        "notify_channel": user.get("notify_channel") or "",
        "has_notify_target": bool(user.get("notify_target")),
    }


def merge_bookmark_ids(*groups: list) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for group in groups:
        for raw in group or []:
            try:
                deal_id = int(raw)
            except (TypeError, ValueError):
                continue
            if deal_id <= 0 or deal_id in seen:
                continue
            seen.add(deal_id)
            out.append(deal_id)
            if len(out) >= MAX_BOOKMARKS:
                return out
    return out


async def list_bookmark_ids(conn, user_id: int) -> list[int]:
    cur = await conn.execute(
        "SELECT deal_id FROM user_bookmarks WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    )
    return [int(r["deal_id"]) for r in await cur.fetchall()]


async def replace_bookmarks(conn, user_id: int, ids: list[int]) -> list[int]:
    clean = merge_bookmark_ids(ids)
    await conn.execute("DELETE FROM user_bookmarks WHERE user_id=?", (user_id,))
    now = utcnow_iso()
    for deal_id in clean:
        await conn.execute(
            "INSERT OR IGNORE INTO user_bookmarks(user_id, deal_id, created_at) VALUES(?,?,?)",
            (user_id, deal_id, now),
        )
    await conn.commit()
    return clean


async def list_keywords(conn, user_id: int) -> list[dict]:
    cur = await conn.execute(
        "SELECT * FROM user_keywords WHERE user_id=? ORDER BY id DESC",
        (user_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def add_keyword(conn, user_id: int, keyword: str, min_grade: str) -> None:
    keyword = " ".join((keyword or "").split())
    if not keyword or len(keyword) > 40:
        raise ValueError("keyword required")
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM user_keywords WHERE user_id=?", (user_id,)
    )
    if int((await cur.fetchone())["c"]) >= MAX_KEYWORDS:
        raise ValueError("too many keywords")
    await conn.execute(
        """
        INSERT INTO user_keywords(user_id, keyword, min_grade, created_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(user_id, keyword) DO UPDATE SET min_grade=excluded.min_grade
        """,
        (user_id, keyword, (min_grade or "핫딜").strip() or "핫딜", utcnow_iso()),
    )


async def delete_keyword(conn, user_id: int, keyword_id: int) -> None:
    await conn.execute(
        "DELETE FROM user_keywords WHERE id=? AND user_id=?",
        (keyword_id, user_id),
    )


async def set_notify(conn, user_id: int, channel: str, target: str) -> None:
    channel = (channel or "").strip().lower()
    target = (target or "").strip()
    if channel and channel not in CHANNELS:
        raise ValueError("channel")
    if channel and not target:
        raise ValueError("target")
    if not channel:
        channel, target = None, None
    await conn.execute(
        "UPDATE users SET notify_channel=?, notify_target=? WHERE id=?",
        (channel, target, user_id),
    )


async def sync_user_alert_subs(conn, user: dict) -> None:
    from app.engine.alerts import add_user_sub, delete_user_subs

    await delete_user_subs(conn, int(user["id"]))
    channel = user.get("notify_channel")
    target = user.get("notify_target")
    if not channel or not target:
        return
    for row in await list_keywords(conn, int(user["id"])):
        await add_user_sub(
            conn,
            user_id=int(user["id"]),
            keyword=row["keyword"],
            min_grade=row.get("min_grade") or "핫딜",
            channel=channel,
            target=target,
        )
