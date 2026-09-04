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
    is_oliveyoung_short,
    is_weak_mall_url,
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
    # FMKorea (XE): the real post body sits in .rd_body/<article>; the header
    # (.rd_hd) carries the 링크·쇼핑몰·상품명·가격·배송 hotdeal_table, which must
    # never end up in body_html — target the article content first.
    "#bd_capture .rd_body article .xe_content",
    "#bd_capture .rd_body .xe_content",
    ".rd_body article .xe_content",
    # FMKorea (XE): FLICK-style — prefer capture root over stray .xe_content.
    "#bd_capture .xe_content",
    "#bd_capture",
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

# Broader shells (.content / article) often wrap nav+comments; keep them for
# mall/thumb harvest but not for body_html.
_BODY_HTML_SKIP = frozenset({".content", "article", "#article"})
_URL_IN_TEXT_RE = re.compile(r"https?://\S+", re.I)

# Board meta rows: prefer these over free-form body links (coupon tips etc.).
BOARD_LINK_LABELS = (
    "구매링크",
    "관련링크",
    "쇼핑링크",
    "상품링크",
    "판매링크",
    "링크",
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
    if blocked and source == "fmkorea":
        enriched = await _enrich_fmkorea_via_browser(client, url)
        if enriched is not None:
            return enriched
    return DetailEnrichment(blocked=blocked)


async def _enrich_fmkorea_via_browser(
    client: PoliteClient, url: str
) -> DetailEnrichment | None:
    """FMKorea detail behind the WASM gate: fetch via headless Chromium."""
    from app.sources import fm_browser

    html = await fm_browser.fetch_html(
        url, want_selector="#bd_capture, .rd_body", timeout=16.0, max_rounds=2
    )
    if not html:
        return None
    parsed = parse_detail(html, url)
    if parsed.mall_url:
        parsed.mall_url = await canonicalize_mall_url(client, parsed.mall_url)
        if parsed.mall_url and is_junk_mall_url(parsed.mall_url):
            parsed.mall_url = None
    if parsed.mall_url or parsed.title or parsed.thumbnail_url or parsed.body_html:
        parsed.blocked = False
        return parsed
    return None


async def canonicalize_mall_url(client: PoliteClient, url: str | None) -> str | None:
    """Turn Coupang partner / Olive Young short links into a normal product URL."""
    if not url or is_junk_mall_url(url):
        return None
    if is_coupang_partner_gate(url):
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
    if is_oliveyoung_short(url):
        try:
            result = await client.get(url, timeout=12.0, max_retries=1, curl_fallback=False)
        except Exception as exc:  # noqa: BLE001
            log.debug("oliveyoung short resolve failed %s: %s", url, exc)
            return url
        final = (result.url or "").strip()
        if final and is_mall_url(final) and not is_oliveyoung_short(final):
            return final
        nested = extract_mall_url(final, result.text or "")
        if nested and not is_oliveyoung_short(nested):
            return nested
        return url
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
    # 1) Board "구매/관련링크" field  2) goToLink / body  3) whole-page fallback.
    # The loose fallback runs on visible text only — the raw page is full of
    # CDN / script / doc URLs that look shop-ish (clipboard.js, css-tricks, …).
    board_mall = _extract_board_field_mall(tree)
    body_mall = _extract_body_mall(tree)
    mall = (
        board_mall
        or extract_goto_shop(html)
        or body_mall
        or extract_mall_url(html, body_text, title)
        or extract_shop_url(body_text, title)
    )
    # Prefer a strong board/body URL over a weak whole-page hit.
    if mall and is_weak_mall_url(mall):
        for candidate in (board_mall, body_mall, extract_goto_shop(html)):
            if candidate and not is_weak_mall_url(candidate):
                mall = candidate
                break
    # Never keep a junk hit (e.g. dealbada dbada.kr/func.php short-link API);
    # leaving mall empty lets enrich_post follow the board link.php redirector.
    if mall and is_junk_mall_url(mall):
        mall = next(
            (c for c in (board_mall, body_mall) if c and not is_junk_mall_url(c)),
            None,
        )
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


def _body_node_score(root) -> tuple[int, int, int]:
    """Rank body candidates: images, then prose (URLs stripped), then raw text."""
    text = " ".join((root.text() or "").split())
    prose = " ".join(_URL_IN_TEXT_RE.sub(" ", text).split())
    imgs = 0
    for img in root.css("img"):
        src = (
            (img.attributes.get("src") or "").strip()
            or (img.attributes.get("data-src") or "").strip()
            or (img.attributes.get("data-original") or "").strip()
        )
        if src and not src.startswith("data:") and "icon" not in src.lower():
            imgs += 1
    return (imgs, len(prose), len(text))


_FIELD_CHROME_CLASSES = frozenset({"hotdeal_table", "rd_hd", "rd_nav_side"})


def _in_field_table(node) -> bool:
    """True when a node lives inside FMKorea's 링크/쇼핑몰/상품명/가격/배송 table
    or the post header chrome — those are structured fields, not the body."""
    parent = node.parent
    depth = 0
    while parent is not None and depth < 12:
        classes = set((parent.attributes.get("class") or "").split())
        if classes & _FIELD_CHROME_CLASSES:
            return True
        parent = parent.parent
        depth += 1
    return False


def _extract_body_html(tree: HTMLParser, page_url: str = "") -> str | None:
    best_raw = ""
    best_score = (-1, -1, -1)
    for sel in BODY_SELECTORS:
        if sel in _BODY_HTML_SKIP:
            continue
        nodes = tree.css(sel)
        if not nodes:
            continue
        # Class-only selectors can hit link fields / signatures; score all.
        # Id / compound selectors are specific enough to take the first hit.
        candidates = [n for n in nodes if not _in_field_table(n)]
        if not candidates:
            continue
        consider = candidates if sel.startswith(".") else candidates[:1]
        local_raw = ""
        local_score = (-1, -1, -1)
        for root in consider:
            raw = _inner_html(root).strip()
            if not raw:
                continue
            score = _body_node_score(root)
            # Skip tiny chrome / empty shells (link-only still has long URL text).
            if score[0] == 0 and score[1] < 12 and score[2] < 12:
                continue
            if score > local_score:
                local_score = score
                local_raw = raw
        if not local_raw:
            continue
        # Prefer richer nodes across selectors (avoids first tiny .xe_content).
        if local_score > best_score:
            best_score = local_score
            best_raw = local_raw
        # Strong FMKorea / board roots: stop once we have real prose or images.
        if sel.startswith("#bd_capture") or sel in {
            "#new_bbs_content",
            ".board-contents",
            ".bbs-contents",
            ".view_content",
        }:
            if best_score[0] > 0 or best_score[1] >= 20:
                break
    if not best_raw:
        return None
    return sanitize_body_html(best_raw, base_url=page_url)


def _label_text(node) -> str:
    return " ".join((node.text() or "").split())


def _is_board_link_label(text: str) -> bool:
    label = (text or "").strip()
    if not label or len(label) > 16:
        return False
    for item in BOARD_LINK_LABELS:
        if item == "링크":
            if label == "링크":
                return True
            continue
        if label == item or label.startswith(item):
            return True
    return False


def _extract_board_field_mall(tree: HTMLParser) -> str | None:
    """Prefer the dedicated board link field over free-form body URLs."""
    weak: str | None = None
    for node in tree.css("th, td, dt, strong, b, span, div, p, li"):
        if not _is_board_link_label(_label_text(node)):
            continue
        container = node.parent or node
        # Prefer the adjacent cell / following siblings inside the same row.
        blobs: list[str] = []
        sibling = node.next
        steps = 0
        while sibling is not None and steps < 4:
            html = sibling.html or ""
            if html:
                blobs.append(html)
            sibling = sibling.next
            steps += 1
        if container is not None and container.html:
            blobs.append(container.html)
        for blob in blobs:
            found = extract_shop_url(blob) or extract_goto_shop(blob)
            if not found or is_junk_mall_url(found):
                continue
            if is_weak_mall_url(found):
                weak = weak or found
                continue
            return found
    return weak


def _extract_body_mall(tree: HTMLParser) -> str | None:
    for sel in BODY_SELECTORS:
        root = tree.css_first(sel)
        if not root:
            continue
        blob = root.html or ""
        if not blob.strip():
            continue
        found = extract_shop_url(blob) or extract_goto_shop(blob)
        if found and not is_junk_mall_url(found):
            return found
    return None
