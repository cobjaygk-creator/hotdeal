"""Coupang Partners Open API client (deep link conversion).

Signing scheme implemented per Coupang Partners' publicly documented
HMAC auth (the "CEA algorithm=HmacSHA256" Authorization header). This
has not been exercised against a live response yet — COUPANG_ENABLED
is False until real keys are configured. Once approved, verify the
deeplink response shape against `create_deeplinks()`'s parsing below
and adjust if the field names differ.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.config import COUPANG_PARTNERS_ACCESS_KEY, COUPANG_PARTNERS_SECRET_KEY

DOMAIN = "https://api-gateway.coupang.com"
DEEPLINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"


def _signed_date() -> str:
    return datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")


def signed_headers(method: str, path_and_query: str) -> dict[str, str]:
    """Build the Authorization + Content-Type headers for a Coupang
    Partners Open API request. `path_and_query` is the path starting
    with '/', including the query string if any (no host)."""
    signed_date = _signed_date()
    message = signed_date + method.upper() + path_and_query
    signature = hmac.new(
        COUPANG_PARTNERS_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        "CEA algorithm=HmacSHA256, "
        f"access-key={COUPANG_PARTNERS_ACCESS_KEY}, "
        f"signed-date={signed_date}, "
        f"signature={signature}"
    )
    return {"Authorization": authorization, "Content-Type": "application/json"}


async def create_deeplinks(urls: list[str]) -> dict[str, str]:
    """Convert coupang.com product URLs into affiliate deep links.

    Returns {original_url: deeplink_url}. URLs the API fails to convert
    are omitted from the result (caller should fall back to the
    original URL for those).
    """
    if not urls:
        return {}
    if not (COUPANG_PARTNERS_ACCESS_KEY and COUPANG_PARTNERS_SECRET_KEY):
        return {}
    body = {"coupangUrls": urls}
    headers = signed_headers("POST", DEEPLINK_PATH)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(DOMAIN + DEEPLINK_PATH, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    out: dict[str, str] = {}
    for row in (data.get("data") or []):
        original = row.get("originalUrl")
        short = row.get("shortenUrl") or row.get("landingUrl")
        if original and short:
            out[original] = short
    return out


def is_coupang_product_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "www.coupang.com" or host.endswith(".coupang.com")
