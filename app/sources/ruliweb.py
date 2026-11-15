from __future__ import annotations

import email.utils
import re
from xml.etree import ElementTree as ET

from app.http_client import PoliteClient
from app.sources import RawPost
from app.sources.html_fetch import fetch_parsed

# RSS is more robust from datacenter IPs than the board HTML.
RSS_URL = "https://bbs.ruliweb.com/market/board/1020/rss"
LIST_URL = RSS_URL  # kept for the debug probe
_ID_RE = re.compile(r"/market/board/\d+/read/(\d+)")
_IMG_RE = re.compile(r"""<img[^>]+src\s*=\s*["']([^"']+)["']""", re.I)


class RuliwebSource:
    name = "ruliweb"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        return await fetch_parsed(
            client, RSS_URL, parse_rss, timeout=20.0, max_retries=1, curl_fallback=False
        )


def parse_rss(xml_text: str) -> list[RawPost]:
    root = ET.fromstring(xml_text)
    posts: list[RawPost] = []
    seen: set[str] = set()
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        m = _ID_RE.search(link)
        if not m:
            continue
        post_id = m.group(1)
        if post_id in seen:
            continue
        title = " ".join((item.findtext("title") or "").split())
        if not title or "공지" in title or "이용안내" in title:
            continue
        seen.add(post_id)
        desc = (item.findtext("description") or "").strip() or None
        author = (item.findtext("author") or "").strip() or None
        posted = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                posted = email.utils.parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted = None
        cat = (item.findtext("category") or "").strip()
        extra: dict = {}
        thumb = _first_thumb(desc)
        if thumb:
            extra["thumbnail_url"] = thumb
        if cat and cat.lower() not in ("", "기타"):
            extra["source_category"] = cat
        posts.append(
            RawPost(
                source="ruliweb",
                source_post_id=post_id,
                url=f"https://bbs.ruliweb.com/market/board/1020/read/{post_id}",
                title=title,
                body=desc,
                author=author,
                posted_at=posted,
                extra=extra,
            )
        )
    return posts


def _first_thumb(desc: str | None) -> str | None:
    if not desc:
        return None
    for m in _IMG_RE.finditer(desc):
        src = (m.group(1) or "").strip()
        if not src or src.startswith("data:"):
            continue
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/"):
            return "https://bbs.ruliweb.com" + src
        if src.startswith("http"):
            return src
    return None
