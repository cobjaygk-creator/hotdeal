from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, unquote, urlparse

HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
# Nested destination inside community redirectors / tracking wrappers.
NESTED_URL_RE = re.compile(
    r"(?:url|target_url|u|href|link|redirect)=((?:https?|https?%3A%2F%2F)[^&\s\"'<>]+)",
    re.I,
)
TRUNCATED_RE = re.compile(r"(?:\.{3}|…|%E2%80%A6)")

MALL_HOST_PARTS = (
    "smartstore.naver.com",
    "brand.naver.com",
    "shopping.naver.com",
    "m.shopping.naver.com",
    "m.site.naver.com",
    "naver.me",
    "coupang.com",
    "link.coupang.com",
    "coupang.cn",
    "11st.co.kr",
    "gmarket.co.kr",
    "gma.me",
    "auction.co.kr",
    "ssg.com",
    "lotteon.com",
    "elm.lotte.com",
    "kurly.com",
    "tmon.co.kr",
    "wemakeprice.com",
    "ohou.se",
    "musinsa.com",
    "ably.co.kr",
    "zigzag.kr",
    "temu.com",
    "aliexpress.com",
    "amazon.",
    "shop.samsung.com",
    "store.kakao.com",
    "gift.kakao.com",
    "shopping.daum.net",
    "oliveyoung.co.kr",
    "hmall.com",
    "gsshop.com",
    "cjmall.com",
    "nsmall.com",
    "halfclub.com",
    "yes24.com",
    "kyobobook.co.kr",
    "interpark.com",
)

COMMUNITY_HOST_PARTS = (
    "ppomppu.co.kr",
    "clien.net",
    "ruliweb.com",
    "quasarzone.com",
    "arca.live",
    "damoang.net",
    "coolenjoy.net",
    "eomisae.co.kr",
    "dealbada.com",
    "fmkorea.com",
    "algumon.com",
    "dealink.co.kr",
    "joobjoob.co.kr",
)


def extract_mall_url(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        for url in _candidate_urls(text):
            for candidate in _expand_candidates(url):
                if is_mall_url(candidate):
                    return candidate
    return None


def is_mall_url(url: str | None) -> bool:
    if not url:
        return False
    raw = html.unescape(url.strip())
    if not raw.startswith(("http://", "https://")):
        return False
    # Display-truncated URLs from community pages (… / ...) are never clickable.
    if TRUNCATED_RE.search(raw):
        return False
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if any(part in host for part in COMMUNITY_HOST_PARTS):
        return False
    if not any(part in host for part in MALL_HOST_PARTS):
        return False
    # Reject bare homepages like https://www.coupang.com/
    path = (parsed.path or "").rstrip("/")
    if not path:
        return False
    # Gmarket/Auction item links without a product id are useless.
    if "gmarket.co.kr" in host or "auction.co.kr" in host:
        qs = parse_qs(parsed.query)
        code = (qs.get("goodscode") or qs.get("itemno") or [""])[0]
        if not str(code).isdigit():
            return False
    return True


def _expand_candidates(url: str) -> list[str]:
    raw = html.unescape(url.strip())
    out = [raw]
    for m in NESTED_URL_RE.finditer(raw):
        nested = unquote(m.group(1).strip())
        if nested.startswith("http"):
            out.append(nested)
    # Common pattern: ?url=https%3A%2F%2F...
    try:
        qs = parse_qs(urlparse(raw).query)
        for key in ("url", "target_url", "u", "href", "link", "redirect"):
            for val in qs.get(key) or []:
                val = unquote(val.strip())
                if val.startswith("http"):
                    out.append(val)
    except ValueError:
        pass
    return out


def _candidate_urls(text: str) -> list[str]:
    decoded = html.unescape(text)
    found: list[str] = []
    for m in HREF_RE.finditer(decoded):
        found.append(m.group(1).strip())
    for m in NESTED_URL_RE.finditer(decoded):
        found.append(unquote(m.group(1).strip()))
    for m in URL_RE.finditer(decoded):
        found.append(m.group(0).rstrip(").,;]'\"}"))
    # de-dupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
