from __future__ import annotations
import base64, hashlib, os
from cryptography.fernet import Fernet

SETTING_KEYS = {
    "NAVER_OAUTH_CLIENT_ID": "네이버 로그인 Client ID",
    "NAVER_OAUTH_CLIENT_SECRET": "네이버 로그인 Client Secret",
    "KAKAO_CLIENT_ID": "카카오 로그인 Client ID",
    "KAKAO_CLIENT_SECRET": "카카오 로그인 Client Secret",
    "GOOGLE_CLIENT_ID": "구글 로그인 Client ID",
    "GOOGLE_CLIENT_SECRET": "구글 로그인 Client Secret",
    "COUPANG_PARTNERS_ACCESS_KEY": "쿠팡 파트너스 Access Key",
    "COUPANG_PARTNERS_SECRET_KEY": "쿠팡 파트너스 Secret Key",
    "TOSS_PARTNERS_KEY": "토스 제휴 키",
    "ADSENSE_PUBLISHER_ID": "Google AdSense Publisher ID",
    "ADSENSE_SIDEBAR_SLOT_ID": "Google 광고 슬롯 ID",
    "ADSENSE_ENABLED": "Google 광고 전체 사용 여부 (1/0)",
}

def _fernet() -> Fernet:
    secret = (os.environ.get("APP_SECRET_KEY") or "").strip()
    if not secret:
        raise RuntimeError("APP_SECRET_KEY가 설정되지 않았습니다")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)

def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()

async def load_runtime_settings(conn) -> int:
    cur = await conn.execute("SELECT key, encrypted_value FROM app_settings")
    rows = await cur.fetchall()
    loaded = 0
    import app.engine.auth as auth_runtime
    import app.config as config_runtime
    import app.coupang.api as coupang_api
    for row in rows:
        try:
            value = decrypt(row["encrypted_value"])
        except Exception:
            continue
        key = row["key"]
        if key in SETTING_KEYS:
            setattr(auth_runtime, key, value)
            setattr(config_runtime, key, value)
            if hasattr(coupang_api, key):
                setattr(coupang_api, key, value)
            loaded += 1
    return loaded