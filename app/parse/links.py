from __future__ import annotations

import base64
import html
import re
from urllib.parse import parse_qs, unquote, urlparse

HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
# Nested destination inside community redirectors / tracking wrappers.
NESTED_URL_RE = re.compile(
    r"(?:url|target[_-]?url|u|href|link|redirect)=((?:https?|https?%3A%2F%2F)[^&\s\"'<>]+)",
    re.I,
)
TRUNCATED_RE = re.compile(r"(?:\.{3}|…|%E2%80%A6)")
# RSS/plain text often glues Korean labels onto short links: naver.me/xxx상품링크
TRAILING_CJK_RE = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3].*$")
# Quasarzone buy button: javascript:goToLink('base64url')
GOTO_LINK_RE = re.compile(r"goToLink\(\s*['\"]([A-Za-z0-9_\-]+=*)['\"]", re.I)

MALL_HOST_PARTS = (
    "smartstore.naver.com",
    "brand.naver.com",
    "shopping.naver.com",
    "m.shopping.naver.com",
    "m.site.naver.com",
    "naver.me",
    "coupang.com",
    "link.coupang.com",
    "coupa.ng",
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
    "oy.run",
    "hmall.com",
    "gsshop.com",
    "cjmall.com",
    "nsmall.com",
    "halfclub.com",
    "yes24.com",
    "kyobobook.co.kr",
    "interpark.com",
    "29cm.co.kr",
    "wconcept.co.kr",
    "kream.co.kr",
    "mustit.co.kr",
    "trenbe.com",
    "iherb.com",
    "qoo10.com",
    "qoo10.jp",
    "lotteimall.com",
    "thehyundai.com",
    "himart.co.kr",
    "e-himart.co.kr",
    "homeplus.co.kr",
    "kakaostyle.com",
    "giftishow.com",
    "11st.kr",
    "brandi.co.kr",
    "hiver.co.kr",
    "eqlstore.com",
    "soldout.co.kr",
    "compuzone.co.kr",
)

# Naver shopping hosts we accept. Everything else under naver.* is ads/login junk.
NAVER_SHOP_HOST_PARTS = (
    "smartstore.naver.com",
    "brand.naver.com",
    "shopping.naver.com",
    "m.shopping.naver.com",
    "m.site.naver.com",
    "naver.me",
)

# Outbound warning pages that prefix the real shop URL.
WRAPPER_HOST_PARTS = (
    "unsafelink.com",
    "href.li",
    "linkvertise.com",
)

JUNK_HOST_PARTS = (
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "t.co",
    "google.com",
    "wikipedia.org",
    "namu.wiki",
    "dcinside.com",
    "imgur.com",
    "github.com",
    "blog.naver.com",
    "m.blog.naver.com",
    "cafe.naver.com",
    "news.naver.com",
    "post.naver.com",
    "tv.naver.com",
    # Naver Search Ads / advertiser portals (often scraped from FMKorea sidebars).
    "saedu.naver.com",
    "searchad.naver.com",
    "adcr.naver.com",
    "nid.naver.com",
    "auth.naver.com",
    "apis.naver.com",
    "api.fixer.io",
    # Ruliweb / community sidebars sometimes inject this affiliate shortener.
    "dajooda.com",
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
    found: list[str] = []
    loose: list[str] = []
    for text in texts:
        if not text:
            continue
        for url in _candidate_urls(text):
            expanded = _expand_candidates(url)
            for candidate in expanded:
                if is_mall_url(candidate):
                    found.append(candidate)
            # Community redirectors may unwrap to a brand shop not on the allow-list.
            if any(part in url.lower() for part in COMMUNITY_HOST_PARTS + WRAPPER_HOST_PARTS):
                for candidate in expanded[1:]:
                    if _is_loose_shop_url(candidate):
                        loose.append(candidate)
    return prefer_mall(found) or prefer_mall(loose)


def extract_goto_shop(text: str | None) -> str | None:
    """Decode Quasarzone javascript:goToLink('base64') buy URLs."""
    if not text:
        return None
    for m in GOTO_LINK_RE.finditer(text):
        decoded = _b64_http_url(m.group(1))
        if decoded and (is_mall_url(decoded) or _is_loose_shop_url(decoded)):
            return decoded
    return None


def extract_shop_url(*texts: str | None) -> str | None:
    """Allow-listed mall first, then a conservative product-looking shop URL."""
    for text in texts:
        goto = extract_goto_shop(text)
        if goto:
            return goto
    found = extract_mall_url(*texts)
    if found:
        return found
    loose: list[str] = []
    for text in texts:
        if not text:
            continue
        for url in _candidate_urls(text):
            for candidate in _expand_candidates(url):
                if _is_loose_shop_url(candidate):
                    loose.append(candidate)
    return prefer_mall(loose)


def prefer_mall(urls: list[str] | None) -> str | None:
    """Pick the most clickable shop URL. Coupang partner gates beat raw PDP links."""
    cleaned = [u for u in (urls or []) if u]
    if not cleaned:
        return None
    return min(cleaned, key=_mall_pref_key)


def prefers_mall(candidate: str | None, current: str | None) -> bool:
    if not candidate or is_junk_mall_url(candidate):
        return False
    if not current or is_junk_mall_url(current):
        return True
    return _mall_pref_key(candidate) < _mall_pref_key(current)


def _mall_pref_key(url: str) -> tuple:
    """Lower is better. Prefer known malls (and Coupang PDPs) over loose unknowns."""
    raw = (url or "").strip().lower()
    try:
        host = (urlparse(raw).hostname or "").lower()
    except ValueError:
        host = ""
    if is_junk_mall_url(url):
        return (9, raw)
    if "coupang.com" in host and "/vp/products/" in raw:
        return (0, raw)
    if "coupang.com" in host and "lptag=" in raw:
        return (1, raw)
    if "coupang.com" in host:
        return (2, raw)
    if host == "coupa.ng" or host.endswith(".coupa.ng") or "link.coupang.com" in host:
        # Partner gates often show "권한이 없습니다" for third-party openers.
        return (5, raw)
    # Allow-listed shop hosts beat unknown "loose" product-looking URLs.
    if is_mall_url(url):
        # Prefer real Olive Young PDPs over oy.run shorteners.
        if "oliveyoung.co.kr" in host:
            return (2, raw)
        if host == "oy.run" or host.endswith(".oy.run"):
            return (4, raw)
        return (3, raw)
    return (6, raw)


def is_coupang_partner_gate(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return False
    return host == "coupa.ng" or host.endswith(".coupa.ng") or host.endswith("link.coupang.com") or host == "link.coupang.com"


def is_oliveyoung_short(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return False
    return host == "oy.run" or host.endswith(".oy.run")


def _host_has(host: str, needle: str) -> bool:
    """Match full host labels, not accidental substrings (t.co ⊂ gmarket.co.kr)."""
    host = (host or "").lower()
    needle = (needle or "").lower()
    if not host or not needle:
        return False
    if needle.endswith("."):
        return needle in host
    return host == needle or host.endswith("." + needle)


def is_junk_mall_url(url: str | None) -> bool:
    if not url:
        return True
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return True
    if not host:
        return True
    if any(_host_has(host, part) for part in JUNK_HOST_PARTS):
        return True
    if (_host_has(host, "naver.com") or _host_has(host, "naver.me")) and not any(
        part in host for part in NAVER_SHOP_HOST_PARTS
    ):
        return True
    path = (parsed.path or "").lower()
    if any(tok in path for tok in ("/adbiz/", "/oauth", "/nidlogin", "/authorize")):
        return True
    return False


def coupang_product_url(url: str | None) -> str | None:
    """Keep product + variant ids; drop noisy tracking when possible."""
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if "coupang.com" not in host:
        return None
    m = re.search(r"/vp/products/(\d+)", parsed.path or "")
    if not m:
        return None
    qs = parse_qs(parsed.query)
    keep = []
    for key in ("itemId", "vendorItemId"):
        vals = qs.get(key) or qs.get(key.lower())
        if vals and vals[0]:
            keep.append(f"{key}={vals[0]}")
    base = f"https://www.coupang.com/vp/products/{m.group(1)}"
    return f"{base}?{'&'.join(keep)}" if keep else base


def _is_loose_shop_url(url: str | None) -> bool:
    if not url or TRUNCATED_RE.search(url):
        return False
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if not host or any(part in host for part in COMMUNITY_HOST_PARTS + WRAPPER_HOST_PARTS):
        return False
    if is_junk_mall_url(url):
        return False
    path = (parsed.path or "").rstrip("/")
    return bool(path)


def is_mall_url(url: str | None) -> bool:
    if not url:
        return False
    raw = html.unescape(url.strip())
    if not raw.startswith(("http://", "https://")):
        return False
    # Display-truncated URLs from community pages (… / ...) are never clickable.
    if TRUNCATED_RE.search(raw):
        return False
    if is_junk_mall_url(raw):
        return False
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if any(part in host for part in COMMUNITY_HOST_PARTS + WRAPPER_HOST_PARTS):
        return False
    if not any(part in host for part in MALL_HOST_PARTS):
        return False
    # Reject bare homepages like https://www.coupang.com/
    path = (parsed.path or "").rstrip("/")
    if not path:
        return False
    # Gmarket/Auction item links without a product id are useless.
    # Affiliate gates (link.gmarket.co.kr) are OK — browser can open them.
    if host.startswith("link.") and "gmarket.co.kr" in host:
        return True
    if "gmarket.co.kr" in host or "auction.co.kr" in host:
        qs = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
        code = (qs.get("goodscode") or qs.get("itemno") or [""])[0]
        if not str(code).isdigit():
            return False
    return True


def _expand_candidates(url: str) -> list[str]:
    raw = _clean_url(url)
    out = [raw]
    wrapper = _unwrap_link_wrapper(raw)
    if wrapper:
        out.append(wrapper)
        out.extend(_expand_candidates(wrapper)[1:])
    unwrapped = _unwrap_ppomppu_target(raw)
    if unwrapped:
        out.append(unwrapped)
    for m in NESTED_URL_RE.finditer(raw):
        nested = unquote(m.group(1).strip())
        if nested.startswith("http"):
            out.append(_clean_url(nested))
    # Common pattern: ?url=https%3A%2F%2F... / target-url=...
    try:
        qs = parse_qs(urlparse(raw).query)
        for key in ("url", "target_url", "target-url", "u", "href", "link", "redirect"):
            for val in qs.get(key) or []:
                val = unquote(val.strip())
                if val.startswith("http"):
                    out.append(_clean_url(val))
                else:
                    # Some boards put base64 destinations in target=.
                    decoded = _b64_http_url(val)
                    if decoded:
                        out.append(decoded)
    except ValueError:
        pass
    return out


def _clean_url(url: str) -> str:
    raw = html.unescape((url or "").strip())
    raw = TRAILING_CJK_RE.sub("", raw)
    return raw.rstrip(").,;]'\"}»>")


def _unwrap_link_wrapper(url: str) -> str | None:
    """Peel unsafelink.com/https://shop... style warning prefixes."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if not host or not any(part in host for part in WRAPPER_HOST_PARTS):
        return None
    # Query string belongs to the inner shop URL, not the wrapper host.
    lower = url.lower()
    host_at = lower.find(host)
    rest = url[host_at + len(host) :].lstrip("/") if host_at >= 0 else ""
    rest = unquote(rest)
    if rest.startswith("http://") or rest.startswith("https://"):
        return _clean_url(rest)
    if rest.startswith("https:/"):
        return _clean_url("https://" + rest[len("https:/") :])
    if rest.startswith("http:/"):
        return _clean_url("http://" + rest[len("http:/") :])
    return None


def _unwrap_ppomppu_target(url: str) -> str | None:
    """Decode s.ppomppu.co.kr / view shortener ?target=<base64 url>."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if "ppomppu.co.kr" not in host:
        return None
    try:
        qs = parse_qs(parsed.query)
    except ValueError:
        return None
    for key in ("target", "url", "u"):
        for val in qs.get(key) or []:
            val = unquote((val or "").strip())
            if val.startswith("http"):
                return _clean_url(val)
            decoded = _b64_http_url(val)
            if decoded:
                return decoded
    return None


def _b64_http_url(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw or len(raw) < 12:
        return None
    pad = "=" * ((4 - len(raw) % 4) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            text = decoder(raw + pad).decode("utf-8", errors="strict").strip()
        except Exception:  # noqa: BLE001
            continue
        if text.startswith("http://") or text.startswith("https://"):
            return _clean_url(text)
    return None


def _candidate_urls(text: str) -> list[str]:
    decoded = html.unescape(text)
    found: list[str] = []
    for m in HREF_RE.finditer(decoded):
        found.append(m.group(1).strip())
    for m in NESTED_URL_RE.finditer(decoded):
        found.append(unquote(m.group(1).strip()))
    for m in URL_RE.finditer(decoded):
        found.append(m.group(0))
    # de-dupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for u in found:
        cleaned = _clean_url(u)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out
