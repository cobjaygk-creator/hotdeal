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
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def _env_flag(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
# Re-enrich already-seen posts that still lack a thumbnail (per source, per collect).
DETAIL_BACKFILL_PER_SOURCE = 5
