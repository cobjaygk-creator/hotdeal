"""Whitelist HTML sanitizer for community post bodies (images allowed)."""
from __future__ import annotations

import re
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

MAX_BODY_HTML = 80_000
MAX_IMAGES = 20

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "hr",
        "div",
        "span",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "ul",
        "ol",
        "li",
        "a",
        "img",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "pre",
        "code",
    }
)
_VOID = frozenset({"br", "hr", "img"})
_DROP_WITH_CHILDREN = frozenset(
    {"script", "style", "iframe", "object", "embed", "form", "input", "button", "textarea", "select", "svg", "math"}
)
_SAFE_SCHEME = re.compile(r"^(https?|mailto):", re.I)
_DANGEROUS_SCHEME = re.compile(r"^\s*(javascript|vbscript|data)\s*:", re.I)


def sanitize_body_html(raw: str | None, *, base_url: str = "", max_len: int = MAX_BODY_HTML) -> str | None:
    """Return safe HTML fragment, or None if empty after cleaning."""
    if not raw or not raw.strip():
        return None
    parser = _BodySanitizer(base_url=base_url or "")
    try:
        parser.feed(raw)
        parser.close()
    except Exception:  # noqa: BLE001
        return None
    out = parser.result().strip()
    if not out:
        return None
    if len(out) > max_len:
        out = out[:max_len].rsplit(">", 1)[0] + ">"
        if not out.endswith("</p>"):
            out += "…"
    # Require some real content (text or at least one image).
    textish = re.sub(r"<[^>]+>", " ", out)
    textish = " ".join(unescape(textish).split())
    if len(textish) < 8 and "<img " not in out.lower():
        return None
    return out


_URL_TEXT_RE = re.compile(r"https?://\S+", re.I)


def is_thin_body_html(html: str | None) -> bool:
    """True when body is empty or basically a buy-link with no prose/images."""
    raw = (html or "").strip()
    if not raw:
        return True
    low = raw.lower()
    if "<img " in low:
        return False
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", raw)).split())
    prose = " ".join(_URL_TEXT_RE.sub(" ", text).split())
    return len(prose) < 40


_FIELD_TABLE_LABELS = ("링크", "쇼핑몰", "상품명", "가격", "배송")
_CHROME_TOKENS = ("조회 수", "추천 수", "비추천", "스크랩", "신고", "댓글로 가기", "위로", "아래로")
_ICON_SRC_PARTS = ("/modules/", "/icons/", "/point/", "emoticon", "/level", "blank.gif", "/addons/")
_DATE_ONLY_RE = re.compile(r"^\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}(\s+\d{1,2}:\d{2}(:\d{2})?)?$")


def _has_content_img(node) -> bool:
    for img in node.css("img"):
        src = (img.attributes.get("src") or img.attributes.get("data-src") or "").lower()
        if src and not any(p in src for p in _ICON_SRC_PARTS):
            return True
    return False


def strip_board_chrome(html: str | None) -> str | None:
    """Drop FMKorea/XE board header + nav + the 링크·쇼핑몰·상품명·가격·배송
    hotdeal_table from a body fragment. Class-independent so it also cleans
    bodies captured before the extractor learned to skip that chrome."""
    raw = (html or "").strip()
    if not raw:
        return html
    lower = raw.lower()
    if "<table" not in lower and not any(t in raw for t in _CHROME_TOKENS[:2]):
        return html
    try:
        from selectolax.parser import HTMLParser as _P

        tree = _P(raw)
    except Exception:  # noqa: BLE001
        return html
    for tbl in tree.css("table"):
        txt = " ".join((tbl.text() or "").split())
        hits = sum(1 for lab in _FIELD_TABLE_LABELS if lab in txt)
        if hits >= 3 and len(txt) < 400:
            tbl.decompose()
    for node in tree.css("h1"):
        node.decompose()
    # Header/nav strips: a small element that is a meta-count row, a nav bar,
    # a bare date, or an author byline (short text + only an avatar/level icon).
    for node in tree.css("div, span, p, ul"):
        try:
            txt = " ".join((node.text() or "").split())
        except Exception:  # noqa: BLE001
            continue
        if len(txt) > 120 or _has_content_img(node):
            continue
        chrome = sum(1 for t in _CHROME_TOKENS if t in txt)
        is_date = bool(_DATE_ONLY_RE.match(txt))
        is_byline = bool(txt) and len(txt) <= 20 and node.css_first("img") is not None
        if chrome >= 2 or is_date or is_byline:
            node.decompose()
    body = tree.body
    parts: list[str] = []
    child = body.child if body else None
    while child is not None:
        if child.html:
            parts.append(child.html)
        child = child.next
    out = "".join(parts).strip()
    if not out or (("<img" not in out.lower()) and len(re.sub(r"<[^>]+>", " ", out).split()) < 4):
        return None
    return out


def prefers_body_html(new: str | None, old: str | None) -> bool:
    """Keep richer community bodies; never replace good prose with link-only."""
    n = (new or "").strip()
    if not n:
        return False
    o = (old or "").strip()
    if not o or is_thin_body_html(o):
        return True
    if is_thin_body_html(n):
        return False
    return len(n) > len(o)


class _BodySanitizer(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._parts: list[str] = []
        self._skip_depth = 0
        self._img_count = 0
        self._open: list[str] = []

    def result(self) -> str:
        # Close any leftover open tags.
        while self._open:
            tag = self._open.pop()
            self._parts.append(f"</{tag}>")
        return "".join(self._parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = (tag or "").lower()
        if self._skip_depth:
            if tag in _DROP_WITH_CHILDREN:
                self._skip_depth += 1
            return
        if tag in _DROP_WITH_CHILDREN:
            self._skip_depth = 1
            return
        if tag not in _ALLOWED_TAGS:
            return
        attr_map = {(k or "").lower(): (v or "") for k, v in attrs}
        if tag == "img":
            html = self._img_tag(attr_map)
            if html:
                self._parts.append(html)
            return
        if tag == "a":
            href = self._safe_url(attr_map.get("href") or "", allow_relative=True)
            if not href:
                self._open.append("span")  # keep text, drop link
                self._parts.append("<span>")
                return
            self._open.append("a")
            self._parts.append(
                f'<a href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">'
            )
            return
        if tag in _VOID:
            self._parts.append(f"<{tag}>")
            return
        self._open.append(tag)
        self._parts.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag = (tag or "").lower()
        if self._skip_depth:
            if tag in _DROP_WITH_CHILDREN:
                self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _VOID or tag not in _ALLOWED_TAGS:
            return
        # Pop until matching tag (tolerates messy community HTML).
        if tag not in self._open:
            return
        while self._open:
            opened = self._open.pop()
            self._parts.append(f"</{opened}>")
            if opened == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        self._parts.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(f"&#{name};")

    def _img_tag(self, attrs: dict[str, str]) -> str | None:
        if self._img_count >= MAX_IMAGES:
            return None
        src = (
            attrs.get("src")
            or attrs.get("data-src")
            or attrs.get("data-original")
            or attrs.get("data-lazy-src")
            or attrs.get("data-url")
            or ""
        ).strip()
        if not src and attrs.get("srcset"):
            src = attrs["srcset"].split(",")[0].strip().split(" ")[0]
        src = self._safe_url(src, allow_relative=True, img=True)
        if not src:
            return None
        self._img_count += 1
        alt = escape((attrs.get("alt") or "")[:200], quote=True)
        return (
            f'<img src="{escape(src, quote=True)}" alt="{alt}" '
            f'loading="lazy" referrerpolicy="no-referrer">'
        )

    def _safe_url(self, raw: str, *, allow_relative: bool = False, img: bool = False) -> str | None:
        url = (raw or "").strip().replace("\x00", "")
        if not url or url.startswith("#"):
            return None
        if _DANGEROUS_SCHEME.match(url):
            return None
        if allow_relative and url.startswith("//") and self.base_url:
            scheme = urlparse(self.base_url).scheme or "https"
            url = f"{scheme}:{url}"
        elif allow_relative and url.startswith("/") and self.base_url:
            url = urljoin(self.base_url, url)
        elif allow_relative and self.base_url and not _SAFE_SCHEME.match(url):
            # Relative path without leading slash (cdn/foo.jpg).
            if ":" not in url.split("?", 1)[0]:
                url = urljoin(self.base_url, url)
        if not _SAFE_SCHEME.match(url):
            return None
        if img and not url.lower().startswith(("http://", "https://")):
            return None
        # Block data: already handled; also skip obvious tracking pixels later if needed.
        if len(url) > 2000:
            return None
        return url
