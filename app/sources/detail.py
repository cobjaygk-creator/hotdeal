from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.config import PPOMPPU_PROXY_URL
from app.http_client import PoliteClient
from app.parse.links import (
    coupang_product_url,
    extract_goto_shop,
    extract_mall_url,
    extract_shop_url,
    is_coupang_partner_gate,
    is_junk_mall_url,
    is_mall_url,
)
from app.parse.sanitize_html import sanitize_body_html
from app.http_client import soft_block_reason
from app.sources.html_fetch import PROXY_FIRST_HOSTS

log = logging.getLogger(__name__)

OUTBOUND_HREF_RE = re.compile(
    r"""href\s*=\s*["']([^"']*(?:link\.php|out\.php|go\.php|click\.php|/link/|redirect|s\.ppomppu\.co\.kr)[^"']*)["']""",
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
    # Sanitized HTML fragment from the community post body (images allowed).
    body_html: str | None = None
    # True only when the detail page was refused/soft-blocked (403, nginx block,
    # Cloudflare gate). A clean fetch that simply has no buy link stays False so
    # callers can tell "exit IP blocked" apart from "post has no mall link".
    blocked: bool = False


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
    host = (urlparse(url).hostname or "").lower()
    prefer_proxy = bool(PPOMPPU_PROXY_URL) and (
        is_ppomppu
        or source in {"quasarzone", "arca", "damoang", "fmkorea"}
        or any(host == item or host.endswith("." + item) for item in PROXY_FIRST_HOSTS)
    )
    # Ppomppu / CF boards: residential proxy first. Others try direct, then proxy.
    proxy_tries: list[str | None] = []
    if prefer_proxy:
        proxy_tries.append(PPOMPPU_PROXY_URL)
        if not is_ppomppu:
            proxy_tries.append(None)
    else:
        proxy_tries.append(None)
        if PPOMPPU_PROXY_URL:
            proxy_tries.append(PPOMPPU_PROXY_URL)
    urls = [url]
    if is_ppomppu and "www.ppomppu.co.kr" in url:
        urls.append(url.replace("www.ppomppu.co.kr", "m.ppomppu.co.kr", 1))
    encoding = "euc-kr" if is_ppomppu else None
    last_err: Exception | None = None
    blocked = False
    for proxy in proxy_tries:
        timeout = 20.0 if proxy else (5.0 if is_ppomppu else None)
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
                    if result.status == 403:
                        blocked = True
                    continue
                if result.status == 403 or _looks_blocked(result.text):
                    blocked = True
                    log.warning("detail enrich blocked source=%s url=%s", source, candidate)
                    continue
                if len(result.text) < 800 and "document.location" in result.text:
                    continue
                parsed = parse_detail(result.text, candidate)
                if not parsed.mall_url:
                    resolved = await resolve_outbound_mall(client, candidate, result.text)
                    if resolved:
                        parsed.mall_url = resolved
                if parsed.mall_url:
                    parsed.mall_url = await canonicalize_mall_url(client, parsed.mall_url)
                if parsed.mall_url and is_junk_mall_url(parsed.mall_url):
                    parsed.mall_url = None
                if parsed.mall_url:
                    parsed.blocked = False
                    return parsed
                # Slim/login shells often have og:title but no buy link. Keep trying.
                if _is_detail_stub(source, result.text):
                    continue
                if parsed.title or parsed.thumbnail_url or parsed.body_html:
                    parsed.blocked = False
                    return parsed
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                log.warning("detail enrich failed source=%s url=%s err=%s", source, candidate, exc)
        if not blocked:
            break
    if last_err:
        log.warning("detail enrich exhausted source=%s url=%s", source, url)
    return DetailEnrichment(blocked=blocked)


async def canonicalize_mall_url(client: PoliteClient, url: str | None) -> str | None:
    """Turn Coupang partner short links into a normal product URL users can open."""
    if not url or is_junk_mall_url(url):
        return None
    if not is_coupang_partner_gate(url):
        return url
    try:
        result = await client.get(url, timeout=12.0, max_retries=1, curl_fallback=False)
    except Exception as exc:  # noqa: BLE001
        log.debug("coupang partner resolve failed %s: %s", url, exc)
        return url
    final = (result.url or "").strip()
    product = coupang_product_url(final)
    if product:
        return product
    if final and is_mall_url(final) and not is_coupang_partner_gate(final):
        return final
    nested = extract_shop_url(final, result.text or "")
    if nested and not is_coupang_partner_gate(nested):
        return coupang_product_url(nested) or nested
    return url


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
                "arca.live",
                "damoang.net",
                "fmkorea.com",
            )
        ):
            continue
        # s.ppomppu.co.kr?target=<base64> can be decoded without an extra hop.
        if "s.ppomppu.co.kr" in host:
            nested = extract_shop_url(abs_url)
            if nested:
                return nested
            continue
        # Skip non-post helpers like board_link.php?type=best
        if not any(tok in abs_url for tok in ("wr_id=", "no=", "idno=", "target=", "url=")):
            continue
        try:
            use_proxy = PPOMPPU_PROXY_URL if "ppomppu.co.kr" in host else None
            result = await client.get(abs_url, timeout=12.0, proxy=use_proxy)
            final = result.url or ""
            nested = extract_shop_url(final, result.text or "")
            if nested:
                return nested
            if is_mall_url(final) or extract_shop_url(final):
                return extract_shop_url(final) or final
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
                r"\s*[-|]\s*(루리웹|뽐뿌|클리앙|퀘이사존|아카라이브|다모앙|쿨엔조이|어미새|딜바다|에펨코리아|펨코).*$",
                "",
                title,
            )
    thumb = _meta_content(tree, "og:image") or _first_img(tree, BODY_SELECTORS)
    if thumb and page_url:
        thumb = urljoin(page_url, thumb)
    body_text = _body_blob(tree)
    mall = extract_goto_shop(html) or extract_shop_url(html, body_text, title)
    body_html = _extract_body_html(tree, page_url)
    return DetailEnrichment(
        title=title or None,
        mall_url=mall,
        thumbnail_url=thumb,
        body_html=body_html,
    )


def _is_detail_stub(source: str, html: str) -> bool:
    if source == "quasarzone":
        return "goToLink(" not in html
    return False


def _looks_blocked(html: str) -> bool:
    return soft_block_reason(html) is not None


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


def _inner_html(node) -> str:
    parts: list[str] = []
    child = node.child
    while child is not None:
        html = child.html
        if html:
            parts.append(html)
        child = child.next
    return "".join(parts)


def _extract_body_html(tree: HTMLParser, page_url: str = "") -> str | None:
    raw = ""
    for sel in BODY_SELECTORS:
        root = tree.css_first(sel)
        if not root:
            continue
        raw = _inner_html(root).strip()
        if not raw:
            continue
        # Skip tiny chrome / empty shells.
        text = " ".join((root.text() or "").split())
        has_img = bool(root.css_first("img"))
        if len(text) < 12 and not has_img:
            continue
        break
    if not raw:
        return None
    return sanitize_body_html(raw, base_url=page_url)
