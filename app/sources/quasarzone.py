from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.sources.html_fetch import fetch_parsed
from app.util.timeparse import parse_int, parse_kr_datetime

LIST_URL = "https://quasarzone.com/bbs/qb_saleinfo"
VIEWS_RE = re.compile(r"/bbs/qb_saleinfo/views/(\d+)")
SKIP_TITLES = ("게시판 안내", "게시판 규정", "이용 안내")
# Shared list placeholder (2020) — not a real product thumb.
_DEFAULT_PREVIEW_MARKERS = ("dc9345db51f5b6aa0e363ed2cfbe9358",)


class QuasarzoneSource:
    name = "quasarzone"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        return await fetch_parsed(client, LIST_URL, parse_list)


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts = _parse_v2_rows(tree)
    if posts:
        return posts
    posts = _parse_market_cards(tree)
    if posts:
        return posts
    return _parse_view_links(tree)


def _parse_v2_rows(tree: HTMLParser) -> list[RawPost]:
    posts: list[RawPost] = []
    seen: set[str] = set()
    for row in tree.css("div.v2-list-row"):
        # Skip notice / non-deal chrome rows.
        if "v2-list-row--hotdeal" not in (row.attributes.get("class") or ""):
            # Older markup may omit the modifier; keep rows that still look like deals.
            if not row.css_first("span.v2-list-row__price") and not row.attributes.get(
                "data-preview"
            ):
                continue
        link = row.css_first("a.subject-link[href*='/views/'], a[href*='/bbs/qb_saleinfo/views/']")
        if not link:
            continue
        href = link.attributes.get("href") or ""
        href_id = _id_from_href(href) or ""
        attr_id = (row.attributes.get("data-qc-id") or "").strip()
        # Title belongs to the subject href. Prefer it when the two ids disagree.
        post_id = href_id or attr_id
        if href_id and attr_id and href_id != attr_id:
            post_id = href_id
        if not post_id or post_id in seen:
            continue
        title = " ".join((link.text() or "").split())
        if not title:
            title = ((link.attributes.get("title") or "") or "").strip()
        if not title or any(skip in title for skip in SKIP_TITLES) or "공지" in title:
            continue
        badge = row.css_first("span.v2-badge")
        badge_txt = " ".join((badge.text() or "").split()) if badge else ""
        if badge_txt == "공지":
            continue
        seen.add(post_id)
        price_el = row.css_first("span.v2-list-row__price")
        price = " ".join((price_el.text() or "").split()) if price_el else ""
        if price and "(" not in title:
            title = f"{title} ({price})"
        nick = row.css_first("[data-nick]")
        comments = row.css_first("span.ctn-count")
        views = row.css_first("span.qc-count-hit")
        date_el = row.css_first("span.v2-list-row__time")
        thumb = (row.attributes.get("data-preview") or "").rstrip("?")
        extra = {}
        if thumb.startswith("http") and not any(m in thumb for m in _DEFAULT_PREVIEW_MARKERS):
            extra["thumbnail_url"] = thumb
        posts.append(
            RawPost(
                source="quasarzone",
                source_post_id=post_id,
                url=f"https://quasarzone.com/bbs/qb_saleinfo/views/{post_id}",
                title=title,
                author=nick.attributes.get("data-nick") if nick else None,
                posted_at=parse_kr_datetime(date_el.text() if date_el else None),
                views=parse_int(views.text() if views else None),
                comments=parse_int(comments.text() if comments else None),
                extra=extra,
            )
        )
    return posts


def _parse_market_cards(tree: HTMLParser) -> list[RawPost]:
    posts: list[RawPost] = []
    seen: set[str] = set()
    for item in tree.css("div.market-info-list, li.market-info-list, div.market-info-list-cont"):
        link = item.css_first("a.subject-link, a[href*='/views/']")
        if not link:
            continue
        href = link.attributes.get("href") or ""
        post_id = _id_from_href(href)
        if not post_id or post_id in seen:
            continue
        label = item.css_first("span.label")
        if label and "공지" in (label.text() or ""):
            continue
        seen.add(post_id)
        title = " ".join((link.text() or "").split())
        if not title:
            title = (link.attributes.get("title") or "").strip()
        price_el = item.css_first("span.text-orange, span.price")
        brand_el = item.css_first("span.brand")
        seller = " ".join((brand_el.text() or "").split()) if brand_el else None
        if price_el:
            price_txt = " ".join((price_el.text() or "").split())
            if price_txt and "(" not in title:
                title = f"{title} ({price_txt})"
        if seller and not title.startswith("["):
            title = f"[{seller}] {title}"
        nick = item.css_first("[data-nick]")
        comments = item.css_first("span.ctn-count")
        views = item.css_first("span.count")
        date_el = item.css_first("span.date")
        posts.append(
            RawPost(
                source="quasarzone",
                source_post_id=post_id,
                url=f"https://quasarzone.com/bbs/qb_saleinfo/views/{post_id}",
                title=title,
                author=nick.attributes.get("data-nick") if nick else None,
                posted_at=parse_kr_datetime(date_el.text() if date_el else None),
                views=parse_int(views.text() if views else None),
                comments=parse_int(comments.text() if comments else None),
            )
        )
    return posts


def _parse_view_links(tree: HTMLParser) -> list[RawPost]:
    """Fallback when card markup changes: harvest /views/{id} anchors."""
    posts: list[RawPost] = []
    seen: set[str] = set()
    for link in tree.css("a[href*='/bbs/qb_saleinfo/views/']"):
        href = link.attributes.get("href") or ""
        m = VIEWS_RE.search(href)
        if not m:
            continue
        post_id = m.group(1)
        if post_id in seen:
            continue
        title = " ".join((link.text() or "").split())
        if not title or len(title) < 4:
            title = (link.attributes.get("title") or "").strip()
        if not title or "공지" in title or any(skip in title for skip in SKIP_TITLES):
            continue
        if title.isdigit() or title in {"다음", "이전", "댓글"}:
            continue
        seen.add(post_id)
        posts.append(
            RawPost(
                source="quasarzone",
                source_post_id=post_id,
                url=urljoin("https://quasarzone.com", href.split("?")[0]),
                title=title,
            )
        )
    return posts


def _id_from_href(href: str) -> str | None:
    m = VIEWS_RE.search(href or "")
    if m:
        return m.group(1)
    parts = href.split("?")[0].rstrip("/").split("/")
    if "views" in parts:
        idx = parts.index("views")
        if idx + 1 < len(parts) and parts[idx + 1].isdigit():
            return parts[idx + 1]
    return next((p for p in reversed(parts) if p.isdigit()), None)
