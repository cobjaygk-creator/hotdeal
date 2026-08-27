from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.util.timeparse import parse_kr_datetime

# robots.txt Disallow: /*?page=  → first page only
LIST_URL = "https://damoang.net/economy"


class DamoangSource:
    name = "damoang"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        result = await client.get(LIST_URL)
        if result.not_modified:
            return []
        return parse_list(result.text)


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    seen: set[str] = set()
    for node in tree.css("a[href^='/economy/']"):
        href = node.attributes.get("href") or ""
        m = re.match(r"/economy/(\d+)/?$", href.split("?")[0])
        if not m:
            continue
        post_id = m.group(1)
        if post_id in seen:
            continue
        title_el = node.css_first("span.post-title")
        title = ""
        if title_el:
            title = title_el.attributes.get("title") or title_el.text() or ""
        title = " ".join(title.split())
        if not title:
            continue
        seen.add(post_id)
        time_el = node.css_first("time") or node.css_first("[datetime]")
        posted = None
        if time_el:
            posted = parse_kr_datetime(
                time_el.attributes.get("datetime") or time_el.text()
            )
        author_el = node.css_first(".post-meta-text")
        posts.append(
            RawPost(
                source="damoang",
                source_post_id=post_id,
                url=f"https://damoang.net/economy/{post_id}",
                title=title,
                author=" ".join((author_el.text() or "").split())[:40] if author_el else None,
                posted_at=posted,
            )
        )
    return posts
