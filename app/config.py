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

MIN_REQUEST_INTERVAL_SEC = 1.0
# Legacy name: unused by the scheduler after source-tier jobs landed.
COLLECT_INTERVAL_MINUTES = 3
PPOMPPU_INTERVAL_SECONDS = int((os.environ.get("PPOMPPU_INTERVAL_SECONDS") or "30").strip() or "30")
COLLECT_FAST_SECONDS = int((os.environ.get("COLLECT_FAST_SECONDS") or "30").strip() or "30")
COLLECT_PROXY_SECONDS = int((os.environ.get("COLLECT_PROXY_SECONDS") or "240").strip() or "240")
COLLECT_SLOW_MINUTES = int((os.environ.get("COLLECT_SLOW_MINUTES") or "30").strip() or "30")
# Quasarzone has no RSS, so its list page is the heaviest proxy fetch left.
# Give it its own (slower) cadence instead of dragging arca down with it.
QUASARZONE_INTERVAL_MINUTES = int(
    (os.environ.get("QUASARZONE_INTERVAL_MINUTES") or "6").strip() or "6"
)
FAMILY_SALE_INTERVAL_MINUTES = 30
AMAZON_JP_INTERVAL_MINUTES = 30
# 알뜰요금제 (이벤트성 MVNO plans, scraped from Moyo theme pages).
MVNO_ENABLED = (os.environ.get("MVNO_ENABLED") or "1").strip().lower() not in (
    "",
    "0",
    "false",
    "no",
)
MVNO_INTERVAL_MINUTES = int(
    (os.environ.get("MVNO_INTERVAL_MINUTES") or "60").strip() or "60"
)
MOYO_THEME_URLS = [
    u.strip()
    for u in (
        os.environ.get("MOYO_THEME_URLS")
        or "https://www.moyoplan.com/plans/themes/one-month-free"
    ).split(",")
    if u.strip()
]
AMAZON_JP_ASSOCIATE_TAG = os.environ.get("AMAZON_JP_ASSOCIATE_TAG", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
ADMIN_USERNAME = (os.environ.get("ADMIN_USERNAME") or "admin").strip() or "admin"
SOLDOUT_REPORT_THRESHOLD = int(os.environ.get("SOLDOUT_REPORT_THRESHOLD") or "3")


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
# Refresh Naver mall price comparison on deal detail after this many hours.
MARKET_COMPARE_CACHE_HOURS = int(os.environ.get("MARKET_COMPARE_CACHE_HOURS") or "6")
# List ticks stay list-only. Buy links / thumbs come from list HTML plus the
# background enrich worker (PPOMPPU_ENRICH_*).
DETAIL_ENRICH_ENABLED = True
DETAIL_BACKFILL_PER_SOURCE = 0
PPOMPPU_DETAIL_PER_TICK = 0
# Residential / Korea proxy for ppomppu detail HTML (buy-link extraction).
# Example: http://user:pass@host:port  or  socks5://host:port
PPOMPPU_PROXY_URL = (os.environ.get("PPOMPPU_PROXY_URL") or "").strip()

# FMKorea fronts /hotdeal with an Akamai + WASM proof-of-work gate that plain
# HTTP clients cannot pass. When enabled, a headless Chromium (Playwright)
# solves the gate and keeps the cleared cookies warm for the process.
FMKOREA_BROWSER_ENABLED = (
    os.environ.get("FMKOREA_BROWSER_ENABLED") or "1"
).strip().lower() not in ("", "0", "false", "no")
# Also route FMKorea *detail* pages through the headless browser when the plain
# fetch is gate-blocked. Off by default: detail enrich runs many times per tick,
# and full browser page loads burn residential-proxy GB fast. List-only is cheap.
FMKOREA_BROWSER_DETAIL = (
    os.environ.get("FMKOREA_BROWSER_DETAIL") or "0"
).strip().lower() not in ("", "0", "false", "no")
# Minimum seconds between any two headless FMKorea fetches (proxy-GB guard).
FMKOREA_BROWSER_MIN_GAP_SEC = int(
    (os.environ.get("FMKOREA_BROWSER_MIN_GAP_SEC") or "45").strip() or "45"
)
# Proxy for the FMKorea browser. Falls back to PPOMPPU_PROXY_URL. Prefer a
# sticky-session endpoint: put "{session}" in the URL and it is replaced with a
# token that rotates every few minutes so one page load stays on one exit IP.
# Example: http://user-session-{session}:pass@gate.provider.com:7000
FMKOREA_PROXY_URL = (
    os.environ.get("FMKOREA_PROXY_URL") or os.environ.get("PPOMPPU_PROXY_URL") or ""
).strip()
FMKOREA_PROXY_SESSION_TTL_SEC = int(
    (os.environ.get("FMKOREA_PROXY_SESSION_TTL_SEC") or "480").strip() or "480"
)
PPOMPPU_ENRICH_INTERVAL_MINUTES = int(
    (os.environ.get("PPOMPPU_ENRICH_INTERVAL_MINUTES") or "5").strip() or "5"
)
MALL_ENRICH_INTERVAL_SECONDS = max(
    15,
    int((os.environ.get("MALL_ENRICH_INTERVAL_SECONDS") or "90").strip() or "90"),
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
