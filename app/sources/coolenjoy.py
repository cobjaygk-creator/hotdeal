from __future__ import annotations

import email.utils
import re
from xml.etree import ElementTree as ET

from app.http_client import PoliteClient
from app.sources import RawPost
from app.sources.html_fetch import fetch_parsed

# The board HTML repeatedly ReadTimeout'd from the cloud host; the RSS feed is
# small, fast, and carries the post body (with images) inline.
RSS_URL = "https://coolenjoy.net/bbs/rss.php?bo_table=jirum"
LIST_URL = RSS_URL  # kept for the debug probe
_ID_RE = re.compile(r"/bbs/jirum/(\d+)")
_IMG_RE = re.compile(r"""<img[^>]+src\s*=\s*["']([^"']+)["']""", re.I)


class CoolenjoySource:
    name = "coolenjoy"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        return await fetch_parsed(client, RSS_URL, parse_rss, timeout=20.0)


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
        if not title or "공지" in title:
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
        extra: dict = {}
        thumb = _first_thumb(desc)
        if thumb:
            extra["thumbnail_url"] = thumb
        posts.append(
            RawPost(
                source="coolenjoy",
                source_post_id=post_id,
                url=f"https://coolenjoy.net/bbs/jirum/{post_id}",
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
            return "https://coolenjoy.net" + src
        if src.startswith("http"):
            return src
    return None
