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