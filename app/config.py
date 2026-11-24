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

# curl_cffi's Chrome-impersonated TLS handshake has been getting reset by
# whatever sits on Railway's outbound path for every proxied host, regardless
# of target site, so it never succeeds there — it just adds a doomed attempt
# (and its own retry) before every proxied request falls through to plain
# httpx anyway. Off by default (keeps existing behavior elsewhere); set to
# "0" on Railway to skip straight to httpx/curl.
CHROME_IMPERSONATE_ENABLED = (os.environ.get("CHROME_IMPERSONATE_ENABLED") or "1").strip().lower() not in (
    "0", "false", "no",
)

MIN_REQUEST_INTERVAL_SEC = 1.0
# Warn when collection stops progressing. Upstream failures must not terminate
# the web process; bounded collector tasks handle recovery independently.
WATCHDOG_ENABLED = (os.environ.get("WATCHDOG_ENABLED") or "1").strip().lower() not in (
    "", "0", "false", "no",
)
WATCHDOG_STALE_MINUTES = int(
    (os.environ.get("WATCHDOG_STALE_MINUTES") or "5").strip() or "5"
)
WATCHDOG_CHECK_SECONDS = int(
    (os.environ.get("WATCHDOG_CHECK_SECONDS") or "60").strip() or "60"
)
# Legacy name: unused by the scheduler after source-tier jobs landed.
COLLECT_INTERVAL_MINUTES = 3
# Polling cadence. November ran these at 30/30/90s, which kept CPU pinned near
# 0.65 vCPU around the clock and made compute 63% of the Railway bill while the
# number of sources stayed flat. The proxy tier is back to the 480s October ran
# on a $10 bill; the two fast tiers stay at 60s, slower than October's 30s,
# since halving their rate costs only about 15 seconds of median latency.
PPOMPPU_INTERVAL_SECONDS = int((os.environ.get("PPOMPPU_INTERVAL_SECONDS") or "60").strip() or "60")
COLLECT_FAST_SECONDS = int((os.environ.get("COLLECT_FAST_SECONDS") or "60").strip() or "60")
COLLECT_PROXY_SECONDS = int((os.environ.get("COLLECT_PROXY_SECONDS") or "480").strip() or "480")
COLLECT_SLOW_MINUTES = int((os.environ.get("COLLECT_SLOW_MINUTES") or "30").strip() or "30")
# Quasarzone has no RSS, so its list page is the heaviest proxy fetch left.
# Give it its own (slower) cadence instead of dragging arca down with it.
QUASARZONE_INTERVAL_MINUTES = int(
    (os.environ.get("QUASARZONE_INTERVAL_MINUTES") or "30").strip() or "30"
)
FAMILY_SALE_INTERVAL_MINUTES = 30
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
ADMIN_USERNAME = (os.environ.get("ADMIN_USERNAME") or "admin").strip() or "admin"
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "").strip()
ADSENSE_PUBLISHER_ID = os.environ.get("ADSENSE_PUBLISHER_ID", "").strip()
ADSENSE_SIDEBAR_SLOT_ID = os.environ.get("ADSENSE_SIDEBAR_SLOT_ID", "").strip()
ADSENSE_MOBILE_SLOT_ID = os.environ.get("ADSENSE_MOBILE_SLOT_ID", "").strip()
ADSENSE_ENABLED = (os.environ.get("ADSENSE_ENABLED", "1").strip().lower() not in ("0", "false", "off", "no"))
ADSENSE_SIDEBAR_ENABLED = (os.environ.get("ADSENSE_SIDEBAR_ENABLED", "1").strip().lower() not in ("0", "false", "off", "no"))
ADSENSE_MOBILE_ENABLED = (os.environ.get("ADSENSE_MOBILE_ENABLED", "1").strip().lower() not in ("0", "false", "off", "no"))
ADSENSE_MAX_PER_PAGE = int(os.environ.get("ADSENSE_MAX_PER_PAGE", "3") or "3")
ADSENSE_START_AT = os.environ.get("ADSENSE_START_AT", "").strip()
ADSENSE_END_AT = os.environ.get("ADSENSE_END_AT", "").strip()
ADSENSE_ESTIMATED_CPC = float(os.environ.get("ADSENSE_ESTIMATED_CPC", "0") or "0")
COUPANG_ESTIMATED_EPC = float(os.environ.get("COUPANG_ESTIMATED_EPC", "0") or "0")
SOLDOUT_REPORT_THRESHOLD = int(os.environ.get("SOLDOUT_REPORT_THRESHOLD") or "3")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Local/company machines stay quiet unless ENABLE_COLLECT=1.
# Render sets RENDER=true; Railway sets RAILWAY_ENVIRONMENT.
ENABLE_COLLECT = (
    _env_flag("ENABLE_COLLECT")
    or _env_flag("RENDER")
    or bool(os.environ.get("RAILWAY_ENVIRONMENT"))
)
HTTP_TIMEOUT_SEC = 20.0
INGEST_SECRET = os.environ.get("INGEST_SECRET", "").strip()
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
DETAIL_ENRICH_ENABLED = True
# Global outbound proxy for all HTTP collection (applied by default to every
# PoliteClient request when set). Per-source vars (PPOMPPU_PROXY_URL,
# FMKOREA_PROXY_URL) take priority when explicitly passed.
# Example: http://user:pass@host:port  or  socks5://user:pass@host:port
HTTP_PROXY_URL = (os.environ.get("HTTP_PROXY_URL") or "").strip()

# Headless Chromium for Quasarzone Cloudflare bypass (mirrors fmkorea pattern).
QUASARZONE_BROWSER_ENABLED = (
    os.environ.get("QUASARZONE_BROWSER_ENABLED") or "1"
).strip().lower() not in ("", "0", "false", "no")
QUASARZONE_BROWSER_MIN_GAP_SEC = int(
    (os.environ.get("QUASARZONE_BROWSER_MIN_GAP_SEC") or "60").strip() or "60"
)
# Proxy for the quasarzone browser. Falls back to HTTP_PROXY_URL.
QUASARZONE_PROXY_URL = (
    os.environ.get("QUASARZONE_PROXY_URL") or HTTP_PROXY_URL or ""
).strip()

# Residential / Korea proxy for ppomppu detail HTML (buy-link extraction).
# Falls back to HTTP_PROXY_URL when not set explicitly.
# Example: http://user:pass@host:port  or  socks5://host:port
PPOMPPU_PROXY_URL = (os.environ.get("PPOMPPU_PROXY_URL") or HTTP_PROXY_URL).strip()

# Proxy for arca.live. The home proxy, like every source except FMKorea: a
# plain fetch of an arca post over it returns the full article and its buy
# link (verified 6/6), so there is no reason to spend metered GB here.
#
# It used to fall back to FMKOREA_PROXY_URL ahead of the home proxy, because
# the arca headless browser needs a non-443 port — Chromium treats a proxy
# port of 443 as TLS and resets the connection. That inherited FMKorea's
# commercial endpoint for all of arca, plain fetches included. The browser is
# only a fallback now (ARCA_BROWSER_DETAIL is off and the list's plain path
# works), so it is not worth routing arca's normal traffic off the home proxy;
# set ARCA_PROXY_URL explicitly to give the browser an alt port again.
ARCA_PROXY_URL = (
    os.environ.get("ARCA_PROXY_URL")
    or PPOMPPU_PROXY_URL
    or os.environ.get("FMKOREA_PROXY_URL")
    or ""
).strip()

# Also route arca.live *detail* pages through the headless browser. Arca fronts
# post pages with the same Cloudflare challenge as its list, so a plain fetch
# only ever returns 403 and the deal keeps its "원문 보기" fallback. Unlike
# FMKorea this runs over the home proxy, so it costs no metered GB.
#
# Default off. The premise above did not hold: a plain fetch of an arca post
# returns the full ~144 KB article and its buy link over either proxy. The
# browser path, meanwhile, has never once succeeded — the home proxy logged 44
# auth rejections for arca.live, one every 30 minutes as the CAPTCHA cooldown
# expired, each attempt earning a fresh Turnstile on the exit IP that the
# working plain path then has to share. Set ARCA_BROWSER_DETAIL=1 to restore it.
ARCA_BROWSER_DETAIL = (
    os.environ.get("ARCA_BROWSER_DETAIL") or "0"
).strip().lower() not in ("", "0", "false", "no")

# Same for quasarzone: its post pages were thought to sit behind the same
# Cloudflare check as its list, so that a plain fetch only ever returned 403
# and the deal never got a buy link.
#
# Default off. That premise held only while Chrome TLS impersonation was
# disabled by a stale Railway variable; with it on, a plain fetch of a
# quasarzone post returns the article and its buy link in about 0.4s
# (verified 2/2). The browser path cost a full Chromium page load — JS, ads,
# analytics — per deal, which is what drove CPU to 63% of the Railway bill
# while the deals themselves stayed flat. Set QUASARZONE_BROWSER_DETAIL=1 to
# restore it if quasarzone ever fronts its posts for real.
QUASARZONE_BROWSER_DETAIL = (
    os.environ.get("QUASARZONE_BROWSER_DETAIL") or "0"
).strip().lower() not in ("", "0", "false", "no")

# FMKorea fronts /hotdeal with an Akamai + WASM proof-of-work gate that plain
# HTTP clients cannot pass. When enabled, a headless Chromium (Playwright)
# solves the gate and keeps the cleared cookies warm for the process.
FMKOREA_BROWSER_ENABLED = (
    os.environ.get("FMKOREA_BROWSER_ENABLED") or "1"
).strip().lower() not in ("", "0", "false", "no")
# Also route FMKorea *detail* pages through the headless browser when the plain
# fetch is gate-blocked. Off by default: detail enrich runs many times per tick,
# and full browser page loads burn residential-proxy GB fast. List-only is cheap.
# Back to off, which is what October ran. It was turned on while Chrome TLS
# impersonation was disabled by a stale Railway variable and plain detail
# fetches could not get through; with impersonation on, a plain fetch returns
# the post and its buy link in under 7s (verified 3/3), so the browser only
# costs CPU and metered proxy GB.
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
    os.environ.get("FMKOREA_PROXY_URL") or os.environ.get("PPOMPPU_PROXY_URL") or HTTP_PROXY_URL or ""
).strip()
FMKOREA_PROXY_SESSION_TTL_SEC = int(
    (os.environ.get("FMKOREA_PROXY_SESSION_TTL_SEC") or "480").strip() or "480"
)
# Headless Chromium is kept warm between fetches so only the first request
# after a launch pays the Cloudflare gate cost, but nothing used to close it:
# an idle browser stayed resident for the whole deployment. Reap it after this
# many idle seconds; the next fetch relaunches and pays the gate once.
BROWSER_IDLE_CLOSE_SECONDS = int(
    (os.environ.get("BROWSER_IDLE_CLOSE_SECONDS") or "600").strip() or "600"
)
BROWSER_IDLE_CHECK_SECONDS = int(
    (os.environ.get("BROWSER_IDLE_CHECK_SECONDS") or "120").strip() or "120"
)
PPOMPPU_ENRICH_INTERVAL_MINUTES = int(
    (os.environ.get("PPOMPPU_ENRICH_INTERVAL_MINUTES") or "10").strip() or "10"
)
# Drain the missing-buy-link backlog from the scheduled enrich job instead of
# only looking at the newest 8 deals per source. Set to a day count to sweep
# every missing-link deal in that window; 0 (default) keeps the normal sweep.
# Meant to be switched on until the backlog clears, then removed.
MALL_BACKFILL_DAYS = int((os.environ.get("MALL_BACKFILL_DAYS") or "0").strip() or "0")

# 300s is what October ran. The 120s November used meant a buy link landed a
# couple of minutes sooner at more than twice the enrich work per hour.
MALL_ENRICH_INTERVAL_SECONDS = max(
    15,
    int((os.environ.get("MALL_ENRICH_INTERVAL_SECONDS") or "300").strip() or "300"),
)
PPOMPPU_ENRICH_BATCH = int((os.environ.get("PPOMPPU_ENRICH_BATCH") or "10").strip() or "10")

# LLM category re-classification. The keyword classifier (app.engine.category)
# still runs inline at collect time; this overrides it in the background when
# the keyword guess was weak (기타) or wrong. Off unless ANTHROPIC_API_KEY set.
# Cost at ~200 new deals/day, batched: well under $0.10/day on Haiku.
ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
# Haiku 4.5 (dated id — proven to resolve on the Messages API). The earlier
# 기타 misfires were mostly the weak prompt, since hardened. Set LLM_MODEL to a
# Sonnet id if quality still lags.
LLM_MODEL = (os.environ.get("LLM_MODEL") or "claude-haiku-4-5-20251001").strip()
# Opt-in: needs the key AND LLM_CLASSIFY_ENABLED=1. The keyword classifier
# runs regardless; the LLM pass costs ~$1/day and is off unless asked for.
LLM_CLASSIFY_ENABLED = bool(ANTHROPIC_API_KEY) and _env_flag(
    "LLM_CLASSIFY_ENABLED", default=False
)
LLM_CLASSIFY_BATCH = int((os.environ.get("LLM_CLASSIFY_BATCH") or "12").strip() or "12")
LLM_CLASSIFY_PER_TICK = int(
    (os.environ.get("LLM_CLASSIFY_PER_TICK") or "100").strip() or "100"
)
LLM_CLASSIFY_INTERVAL_SECONDS = max(
    30,
    int((os.environ.get("LLM_CLASSIFY_INTERVAL_SECONDS") or "120").strip() or "120"),
)

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
NAVER_OAUTH_CLIENT_ID = os.environ.get("NAVER_OAUTH_CLIENT_ID", "").strip()
NAVER_OAUTH_CLIENT_SECRET = os.environ.get("NAVER_OAUTH_CLIENT_SECRET", "").strip()

COUPANG_PARTNERS_ACCESS_KEY = os.environ.get("COUPANG_PARTNERS_ACCESS_KEY", "").strip()
COUPANG_PARTNERS_SECRET_KEY = os.environ.get("COUPANG_PARTNERS_SECRET_KEY", "").strip()
COUPANG_ENABLED = bool(COUPANG_PARTNERS_ACCESS_KEY and COUPANG_PARTNERS_SECRET_KEY)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT = (os.environ.get("VAPID_SUBJECT") or "mailto:admin@example.com").strip()
WEBPUSH_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int((os.environ.get("SMTP_PORT") or "587").strip() or "587")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = (os.environ.get("SMTP_FROM") or SMTP_USER).strip()
SMTP_STARTTLS = (os.environ.get("SMTP_STARTTLS") or "1").strip().lower() not in ("", "0", "false", "no")
# Local KST hour (0-23) the daily digest goes out.
EMAIL_DIGEST_HOUR = int((os.environ.get("EMAIL_DIGEST_HOUR") or "8").strip() or "8")
EMAIL_DIGEST_ENABLED = bool(SMTP_HOST and SMTP_FROM)




