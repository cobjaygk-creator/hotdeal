from __future__ import annotations

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.util.timeparse import parse_int, parse_kr_datetime

# robots.txt Disallow: /*?*  → first page only, no query string
LIST_URL = "https://www.clien.net/service/board/jirum"


class ClienSource:
    name = "clien"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        result = await client.get(LIST_URL)
        if result.not_modified:
            return []
        return parse_list(result.text)


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    for row in tree.css('div.list_item[data-role="list-row"]'):
        post_id = row.attributes.get("data-board-sn")
        title_a = row.css_first('a[data-role="list-title-text"]')
        if not post_id or not title_a:
            continue
        title = " ".join((title_a.text() or "").split())
        author = row.attributes.get("data-author-id")
        ts = row.css_first("span.timestamp")
        votes_el = row.css_first("div.list_symph em")
        views_el = row.css_first("div.list_hit span.hit")
        comments = parse_int(row.attributes.get("data-comment-count"))
        posts.append(
            RawPost(
                source="clien",
                source_post_id=post_id,
                url=f"https://www.clien.net/service/board/jirum/{post_id}",
                title=title,
                author=author,
                posted_at=parse_kr_datetime(ts.text() if ts else None),
                votes=parse_int(votes_el.text() if votes_el else None),
                views=parse_int(views_el.text() if views_el else None),
                comments=comments,
            )
        )
    return posts
