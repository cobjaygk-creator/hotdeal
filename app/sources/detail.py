from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.parse.links import extract_mall_url

log = logging.getLogger(__name__)

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


async def enrich_post(client: PoliteClient, source: str, url: str) -> DetailEnrichment:
    if not url or not url.startswith(("http://", "https://")):
        return DetailEnrichment()
    try:
        # Ppomppu detail pages are often euc-kr.
        encoding = "euc-kr" if "ppomppu.co.kr" in url else None
        result = await client.get(url, encoding=encoding)
        if result.not_modified or not result.text:
            return DetailEnrichment()
        return parse_detail(result.text, url)
    except Exception as exc:  # noqa: BLE001
        log.warning("detail enrich failed source=%s url=%s err=%s", source, url, exc)
        return DetailEnrichment()


def parse_detail(html: str, page_url: str = "") -> DetailEnrichment:
    tree = HTMLParser(html)
    title = _meta_content(tree, "og:title") or _first_text(tree, TITLE_SELECTORS)
    if title:
        title = " ".join(title.split())
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
