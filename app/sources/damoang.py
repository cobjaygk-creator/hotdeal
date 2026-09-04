from __future__ import annotations

import email.utils
import re
from xml.etree import ElementTree as ET

from app.http_client import PoliteClient
from app.sources import RawPost
from app.sources.html_fetch import fetch_parsed

# The "경제" board = domestic hot-deal board. RSS is ~15 KB vs a ~300 KB list
# page; damoang.net is Cloudflare-fronted so this still goes proxy-first.
RSS_URL = "https://damoang.net/rss/economy"
LIST_URL = RSS_URL  # kept for the debug probe
_ID_RE = re.compile(r"/economy/(\d+)")


class DamoangSource:
    name = "damoang"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        return await fetch_parsed(client, RSS_URL, parse_rss)


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
        if not title:
            continue
        seen.add(post_id)
        desc = " ".join((item.findtext("description") or "").split()) or None
        author = (item.findtext("author") or "").strip() or None
        posted = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                posted = email.utils.parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted = None
        posts.append(
            RawPost(
                source="damoang",
                source_post_id=post_id,
                url=f"https://damoang.net/economy/{post_id}",
                title=title,
                body=desc,
                author=author[:40] if author else None,
                posted_at=posted,
            )
        )
    return posts
