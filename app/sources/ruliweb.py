from __future__ import annotations

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.util.timeparse import parse_int, parse_kr_datetime

# robots.txt blocks ?view= and ?orderby= — use the default URL only
LIST_URL = "https://bbs.ruliweb.com/market/board/1020"


class RuliwebSource:
    name = "ruliweb"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        result = await client.get(LIST_URL)
        if result.not_modified:
            return []
        return parse_list(result.text)


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    for row in tree.css("tr.table_body.blocktarget"):
        id_td = row.css_first("td.id")
        title_a = row.css_first("a.subject_link")
        if not id_td or not title_a:
            continue
        post_id = (id_td.text() or "").strip()
        if not post_id.isdigit():
            continue
        title = (title_a.attributes.get("title") or "").strip()
        if not title:
            title = " ".join((title_a.text() or "").split())
        else:
            title = " ".join(title.split())
        writer = row.css_first("td.writer a")
        rec = row.css_first("td.recomd")
        hit = row.css_first("td.hit")
        time_el = row.css_first("td.time")
        posts.append(
            RawPost(
                source="ruliweb",
                source_post_id=post_id,
                url=f"https://bbs.ruliweb.com/market/board/1020/read/{post_id}",
                title=title,
                author=" ".join((writer.text() or "").split()) if writer else None,
                posted_at=parse_kr_datetime(time_el.text() if time_el else None),
                votes=parse_int(rec.text() if rec else None),
                views=parse_int(hit.text() if hit else None),
            )
        )
    return posts
