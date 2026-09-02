from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.sources.html_fetch import fetch_parsed
from app.util.timeparse import parse_int, parse_kr_datetime

LIST_URL = "https://coolenjoy.net/bbs/jirum"


class CoolenjoySource:
    name = "coolenjoy"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        # coolenjoy often stalls on cloud hosts; allow a longer read.
        return await fetch_parsed(client, LIST_URL, parse_list, timeout=60.0)


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    seen: set[str] = set()
    for row in tree.css("li.d-md-table-row"):
        title_a = row.css_first("a.na-subject")
        if not title_a:
            continue
        href = title_a.attributes.get("href") or ""
        m = re.search(r"/bbs/jirum/(\d+)", href)
        if not m:
            continue
        post_id = m.group(1)
        if post_id in seen:
            continue
        title = " ".join((title_a.text() or "").split())
        if not title or "공지" in title:
            continue
        seen.add(post_id)
        price_el = row.css_first("font")
        price_txt = " ".join((price_el.text() or "").split()) if price_el else ""
        if price_txt and "(" not in title:
            title = f"{title} ({price_txt})"
        author_el = row.css_first("a.sv_member")
        date_txt = _labeled(row, "등록일")
        views_txt = _labeled(row, "조회")
        votes_txt = _labeled(row, "추천")
        comments_el = row.css_first("span.count-plus")
        posts.append(
            RawPost(
                source="coolenjoy",
                source_post_id=post_id,
                url=f"https://coolenjoy.net/bbs/jirum/{post_id}",
                title=title,
                author=" ".join((author_el.text() or "").split()) if author_el else None,
                posted_at=parse_kr_datetime(date_txt),
                votes=parse_int(votes_txt),
                views=parse_int(views_txt),
                comments=parse_int(comments_el.text() if comments_el else None),
            )
        )
    return posts


def _labeled(row, label: str) -> str | None:
    for span in row.css("span.sr-only"):
        if (span.text() or "").strip() != label:
            continue
        parent = span.parent
        if not parent:
            return None
        text = " ".join((parent.text() or "").split())
        return text.replace(label, "").strip() or None
    return None
