from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.sources.html_fetch import fetch_parsed
from app.util.timeparse import parse_int, parse_kr_datetime

# First page only. Avoid search/listStyle query strings.
LIST_URL = "https://www.fmkorea.com/hotdeal"
SKIP_TITLES = ("이용규칙", "이용 규칙", "이용안내", "자료실", "자동설치")


class FmkoreaSource:
    name = "fmkorea"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        try:
            return await fetch_parsed(client, LIST_URL, parse_list)
        except RuntimeError as exc:
            msg = str(exc)
            if "blocked:" not in msg and "parsed 0 posts" not in msg:
                raise
            # Akamai + WASM gate: fall back to the headless-browser fetcher.
            from app.sources import fm_browser

            html = await fm_browser.fetch_html(
                LIST_URL, want_selector="li.li h3.title a[href]"
            )
            if not html:
                raise
            posts = parse_list(html)
            if not posts:
                raise RuntimeError(f"fmkorea browser parsed 0 posts ({LIST_URL})") from exc
            return posts


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    seen: set[str] = set()
    for row in tree.css("li.li"):
        title_a = row.css_first("h3.title a[href]")
        if not title_a:
            continue
        href = (title_a.attributes.get("href") or "").split("#")[0]
        post_id = _id_from_href(href)
        if not post_id or post_id in seen:
            continue
        title_el = title_a.css_first("span.ellipsis-target")
        title = " ".join(((title_el.text() if title_el else title_a.text()) or "").split())
        title = re.sub(r"\s*\[\d+\]\s*$", "", title)
        if not title or any(skip in title for skip in SKIP_TITLES):
            continue
        seen.add(post_id)
        seller = _info_value(row, "쇼핑몰")
        price = _info_value(row, "가격")
        delivery = _info_value(row, "배송")
        extra_bits = [bit for bit in (price, delivery) if bit]
        if seller and not title.startswith("["):
            title = f"[{seller}] {title}"
        if extra_bits and "(" not in title:
            title = f"{title} ({' / '.join(extra_bits)})"
        author_el = row.css_first("span.author")
        author = " ".join((author_el.text() or "").split()).lstrip("/ ").strip() or None
        comments_el = row.css_first("span.comment_count")
        thumb = _thumb(row)
        extra = {"thumbnail_url": thumb} if thumb else {}
        reg = row.css_first("span.regdate")
        posts.append(
            RawPost(
                source="fmkorea",
                source_post_id=post_id,
                url=f"https://www.fmkorea.com/{post_id}",
                title=title,
                author=author,
                posted_at=parse_kr_datetime(
                    " ".join((reg.text() or "").split()) if reg else None
                ),
                comments=parse_int(comments_el.text() if comments_el else None),
                extra=extra,
            )
        )
    return posts


def _id_from_href(href: str) -> str | None:
    m = re.search(r"document_srl=(\d+)", href)
    if m:
        return m.group(1)
    m = re.search(r"/(\d{6,})/?$", href.split("?")[0])
    return m.group(1) if m else None


def _info_value(row, label: str) -> str | None:
    info = row.css_first("div.hotdeal_info")
    if not info:
        return None
    for span in info.css("span"):
        text = " ".join((span.text() or "").split())
        if text.startswith(label):
            strong = span.css_first("a.strong") or span.css_first(".strong")
            val = " ".join(((strong.text() if strong else text.split(":", 1)[-1]) or "").split())
            return val or None
    return None


def _thumb(row) -> str | None:
    img = row.css_first("img.thumb")
    if not img:
        return None
    src = (img.attributes.get("data-original") or img.attributes.get("src") or "").strip()
    if not src or "transparent" in src or src.startswith("data:"):
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://image.fmkorea.com" + src
    return src
