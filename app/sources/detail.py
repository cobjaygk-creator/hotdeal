from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.config import PPOMPPU_PROXY_URL
from app.http_client import PoliteClient
from app.parse.links import extract_mall_url, is_mall_url

log = logging.getLogger(__name__)

OUTBOUND_HREF_RE = re.compile(
    r"""href\s*=\s*["']([^"']*(?:link\.php|out\.php|/link/|redirect|s\.ppomppu\.co\.kr)[^"']*)["']""",
    re.I,
)

TITLE_SELECTORS = (
    "h1",
    ".subject",
    ".subject_text",
    ".view_title",
    ".board-view-title",
    ".article-title",
    ".title",
    "meta[property='og:title']",
)

BODY_SELECTORS = (
    "#new_bbs_content",
    ".board-contents",
    ".bbs-contents",
    ".view_content",
    ".article-body",
    ".article_content",
    ".xe_content",
    "#bo_v_con",
    ".content",
    "article",
    "#article",
    "td.han",
    "#article_1",
)

IMG_SRC_RE = re.compile(r"""<img[^>]+src\s*=\s*["']([^"']+)["']""", re.I)


@dataclass
class DetailEnrichment:
    title: str | None = None
    mall_url: str | None = None
    thumbnail_url: str | None = None


_BLOCKED_TITLE = re.compile(
    r"^(403\s*forbidden|401\s*unauthorized|404\s*not\s*found|just a moment|access denied|attention required)\b",
    re.I,
)


async def enrich_post(client: PoliteClient, source: str, url: str) -> DetailEnrichment:
    if not url or not url.startswith(("http://", "https://")):
        return DetailEnrichment()
    is_ppomppu = source == "ppomppu" or "ppomppu.co.kr" in url
    # Prefer https; ppomppu RSS still emits http:// links that bounce via script.
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    proxy = PPOMPPU_PROXY_URL if is_ppomppu and PPOMPPU_PROXY_URL else None
    # Without a proxy: one short direct attempt (collect must stay fast).
    # With residential proxy: allow a fuller fetch like hotdeal.zip-style scrapers.
    urls = [url]
    if is_ppomppu and proxy and "www.ppomppu.co.kr" in url:
        urls.append(url.replace("www.ppomppu.co.kr", "m.ppomppu.co.kr", 1))
    timeout = 20.0 if proxy else (5.0 if is_ppomppu else None)
    encoding = "euc-kr" if is_ppomppu else None
    last_err: Exception | None = None
    for candidate in urls:
        try:
            result = await client.get(
                candidate,
                encoding=encoding,
                timeout=timeout,
                curl_fallback=(not is_ppomppu) or bool(proxy),
                max_retries=2 if proxy else (1 if is_ppomppu else None),
                proxy=proxy,
            )
            if result.not_modified or not result.text:
                continue
            if _looks_blocked(result.text):
                log.warning("detail enrich blocked source=%s url=%s", source, candidate)
                continue
            # Tiny redirect shells are not useful article HTML.
            if len(result.text) < 800 and "document.location" in result.text:
                continue
            parsed = parse_detail(result.text, candidate)
            if not parsed.mall_url:
                resolved = await resolve_outbound_mall(client, candidate, result.text)
                if resolved:
                    parsed.mall_url = resolved
            if parsed.title or parsed.mall_url or parsed.thumbnail_url:
                return parsed
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.warning("detail enrich failed source=%s url=%s err=%s", source, candidate, exc)
    if last_err:
        log.warning("detail enrich exhausted source=%s url=%s", source, url)
    return DetailEnrichment()


async def resolve_outbound_mall(
    client: PoliteClient, page_url: str, html: str
) -> str | None:
    """Follow community redirectors (e.g. dealbada link.php) to the mall URL."""
    seen: set[str] = set()
    for m in OUTBOUND_HREF_RE.finditer(html or ""):
        href = (m.group(1) or "").replace("&amp;", "&").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        abs_url = urljoin(page_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        # Only follow same-community outbound helpers, not random links.
        host = (abs_url.split("/")[2] if "://" in abs_url else "").lower()
        if not any(
            part in host
            for part in (
                "dealbada.com",
                "clien.net",
                "eomisae.co.kr",
                "ruliweb.com",
                "ppomppu.co.kr",
                "coolenjoy.net",
                "quasarzone.com",
            )
        ):
            continue
        # s.ppomppu.co.kr?target=<base64> can be decoded without an extra hop.
        if "s.ppomppu.co.kr" in host:
            nested = extract_mall_url(abs_url)
            if nested:
                return nested
            continue
        # Skip non-post helpers like board_link.php?type=best
        if "wr_id=" not in abs_url and "no=" not in abs_url:
            continue
        try:
            result = await client.get(abs_url, timeout=12.0)
            final = result.url or ""
            # Prefer unwrapped item URL inside affiliate gates when present.
            nested = extract_mall_url(final, result.text or "")
            if nested:
                return nested
            if is_mall_url(final):
                return final
        except Exception as exc:  # noqa: BLE001
            log.debug("outbound resolve failed %s: %s", abs_url, exc)
        if len(seen) >= 3:
            break
    return None


def parse_detail(html: str, page_url: str = "") -> DetailEnrichment:
    if _looks_blocked(html):
        return DetailEnrichment()
    tree = HTMLParser(html)
    title = _meta_content(tree, "og:title") or _first_text(tree, TITLE_SELECTORS)
    if title:
        title = " ".join(title.split())
        if _BLOCKED_TITLE.match(title):
            title = None
        else:
            title = re.sub(
                r"\s*[-|]\s*(루리웹|뽐뿌|클리앙|퀘이사존|아카라이브|다모앙|쿨엔조이|어미새|딜바다).*$",
                "",
                title,
            )
    thumb = _meta_content(tree, "og:image") or _first_img(tree, BODY_SELECTORS)
    if thumb and page_url:
        thumb = urljoin(page_url, thumb)
    body_text = _body_blob(tree)
    mall = extract_mall_url(body_text, html[:50000], title)
    return DetailEnrichment(title=title or None, mall_url=mall, thumbnail_url=thumb)


def _looks_blocked(html: str) -> bool:
    head = html[:1500].lower()
    return any(
        token in head
        for token in (
            "403 forbidden",
            "just a moment",
            "cf-browser-verification",
            "access denied",
            "attention required",
            "요청을 차단",
        )
    )


def enrich_from_list_body(body: str | None) -> DetailEnrichment:
    """Cheap extract from RSS/list description without a detail fetch."""
    if not body:
        return DetailEnrichment()
    mall = extract_mall_url(body)
    thumb = None
    m = IMG_SRC_RE.search(body)
    if m:
        src = m.group(1).strip()
        if src and not src.startswith("data:"):
            thumb = src
    return DetailEnrichment(mall_url=mall, thumbnail_url=thumb)


def _meta_content(tree: HTMLParser, prop: str) -> str | None:
    for sel in (f'meta[property="{prop}"]', f"meta[property='{prop}']", f'meta[name="{prop}"]'):
        node = tree.css_first(sel)
        if node:
            val = (node.attributes.get("content") or "").strip()
            if val:
                return val
    return None


def _first_text(tree: HTMLParser, selectors: tuple[str, ...]) -> str | None:
    for sel in selectors:
        if sel.startswith("meta"):
            node = tree.css_first(sel)
            if node:
                val = (node.attributes.get("content") or "").strip()
                if val:
                    return val
            continue
        node = tree.css_first(sel)
        if node:
            text = " ".join((node.text() or "").split())
            if text and len(text) >= 4:
                return text
    return None


def _first_img(tree: HTMLParser, selectors: tuple[str, ...]) -> str | None:
    for sel in selectors:
        root = tree.css_first(sel)
        if not root:
            continue
        for img in root.css("img[src]"):
            src = (img.attributes.get("src") or "").strip()
            if src and not src.startswith("data:") and "icon" not in src.lower():
                return src
    for img in tree.css("img[src]"):
        src = (img.attributes.get("src") or "").strip()
        if src and not src.startswith("data:") and "icon" not in src.lower():
            return src
    return None


def _body_blob(tree: HTMLParser) -> str:
    chunks: list[str] = []
    for sel in BODY_SELECTORS:
        root = tree.css_first(sel)
        if not root:
            continue
        for a in root.css("a[href]"):
            href = (a.attributes.get("href") or "").strip()
            if href:
                chunks.append(href)
        for a in root.css("[data-url], [data-href], [data-link]"):
            for key in ("data-url", "data-href", "data-link"):
                href = (a.attributes.get(key) or "").strip()
                if href:
                    chunks.append(href)
        text = " ".join((root.text() or "").split())
        if text:
            chunks.append(text[:4000])
        if chunks:
            break
    # Fallback: harvest all outbound http(s) anchors on the page.
    if not chunks:
        for a in tree.css("a[href^='http']"):
            href = (a.attributes.get("href") or "").strip()
            if href:
                chunks.append(href)
    return "\n".join(chunks)
