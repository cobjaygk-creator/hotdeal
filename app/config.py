import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _resolve_data_dir() -> Path:
    # Prefer explicit override, then Railway volume mount, then repo-local data/.
    for key in ("DATA_DIR", "RAILWAY_VOLUME_MOUNT_PATH"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw)
    return ROOT_DIR / "data"


DATA_DIR = _resolve_data_dir()
DATABASE_PATH = DATA_DIR / "hotdeal.db"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

MIN_REQUEST_INTERVAL_SEC = 2.0
COLLECT_INTERVAL_MINUTES = 3
PPOMPPU_INTERVAL_SECONDS = 60
FAMILY_SALE_INTERVAL_MINUTES = 30
AMAZON_JP_INTERVAL_MINUTES = 30
AMAZON_JP_ASSOCIATE_TAG = os.environ.get("AMAZON_JP_ASSOCIATE_TAG", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Hidden for now; set AMAZON_JP_ENABLED=1 to show nav + schedule again.
AMAZON_JP_ENABLED = _env_flag("AMAZON_JP_ENABLED", default=False)


# Local/company machines stay quiet unless ENABLE_COLLECT=1.
# Render sets RENDER=true; Railway sets RAILWAY_ENVIRONMENT.
ENABLE_COLLECT = (
    _env_flag("ENABLE_COLLECT")
    or _env_flag("RENDER")
    or bool(os.environ.get("RAILWAY_ENVIRONMENT"))
)
HTTP_TIMEOUT_SEC = 20.0
MAX_RETRIES = 3

BASELINE_DAYS = 90
MIN_BASELINE_SAMPLES = 3
DEDUPE_HOURS = 24
JACCARD_THRESHOLD = 0.7
PRICE_DELTA = 0.03
COOLDOWN_HOURS = 24
RECENT_DEAL_HOURS = 48

ANOMALY_DROP_RATIO = 0.70
MIN_SANE_PRICE = 1000

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "").strip()
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
NAVER_SEED_ENABLED = bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)
NAVER_SEED_CACHE_DAYS = 7
NAVER_SEED_MIN_SIMILARITY = 0.35
DETAIL_ENRICH_ENABLED = True
# Re-enrich already-seen posts that still lack thumbnail or mall_url.
DETAIL_BACKFILL_PER_SOURCE = 8
# Ppomppu detail pages are often blocked from datacenter IPs; keep in-tick attempts tiny
# so the 60s RSS collect cannot stall. Prefer PPOMPPU_PROXY_URL + background enrich.
PPOMPPU_DETAIL_PER_TICK = 2
# Residential / Korea proxy for ppomppu detail HTML (buy-link extraction).
# Example: http://user:pass@host:port  or  socks5://host:port
PPOMPPU_PROXY_URL = (os.environ.get("PPOMPPU_PROXY_URL") or "").strip()
PPOMPPU_ENRICH_INTERVAL_MINUTES = int(
    (os.environ.get("PPOMPPU_ENRICH_INTERVAL_MINUTES") or "5").strip() or "5"
)
PPOMPPU_ENRICH_BATCH = int((os.environ.get("PPOMPPU_ENRICH_BATCH") or "12").strip() or "12")

SITE_URL = (os.environ.get("SITE_URL") or "").strip().rstrip("/")
if not SITE_URL:
    domain = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    SITE_URL = f"https://{domain}" if domain else "https://hotdeal-production.up.railway.app"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
ALERT_KEYWORDS = os.environ.get("ALERT_KEYWORDS", "").strip()
ALERT_MIN_GRADE = os.environ.get("ALERT_MIN_GRADE", "핫딜").strip() or "핫딜"

SESSION_SECRET = (
    os.environ.get("SESSION_SECRET") or ADMIN_PASSWORD or "hotdeal-dev-session"
).strip()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
KAKAO_CLIENT_ID = (
    os.environ.get("KAKAO_CLIENT_ID") or os.environ.get("KAKAO_REST_API_KEY") or ""
).strip()
KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
