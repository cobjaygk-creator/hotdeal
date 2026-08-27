from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.util.timeparse import parse_int, parse_kr_datetime

# robots.txt: no query strings, crawl-delay 5. First page only.
BOARDS = (
    ("fs", "https://eomisae.co.kr/fs"),
    ("rt", "https://eomisae.co.kr/rt"),
)
SKIP_TITLES = ("이용 규정", "상품권 이벤트", "list_adsense")


class EomisaeSource:
    name = "eomisae"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        posts: list[RawPost] = []
        seen: set[str] = set()
        for _board, url in BOARDS:
            result = await client.get(url)
            if result.not_modified:
                continue
            for post in parse_list(result.text):
                if post.source_post_id in seen:
                    continue
                seen.add(post.source_post_id)
                posts.append(post)
        return posts


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    seen: set[str] = set()
    for link in tree.css("a.pjax"):
        href = (link.attributes.get("href") or "").split("#")[0]
        m = re.fullmatch(r"/(fs|rt|os)/(\d+)", href)
        if not m:
            continue
        board, post_id = m.group(1), m.group(2)
        if post_id in seen:
            continue
        title = " ".join((link.text() or "").split())
        if not title or title.isdigit() or any(s in title for s in SKIP_TITLES):
            continue
        row = link.parent
        while row and row.tag != "tr":
            row = row.parent
        cate = row.css_first("span.cate") if row else None
        cate_txt = " ".join((cate.text() or "").split()) if cate else ""
        if any(skip in cate_txt for skip in ("공지", "AD", "광고")):
            continue
        tds = row.css("td") if row else []
        date_txt = tds[-2].text() if len(tds) >= 2 else None
        votes_td = tds[-1].text() if tds else None
        comments_a = row.css_first("a.tt_cm") if row else None
        author_a = row.css_first("a[href='#popup_menu_area']") if row else None
        seen.add(post_id)
        posts.append(
            RawPost(
                source="eomisae",
                source_post_id=post_id,
                url=f"https://eomisae.co.kr/{board}/{post_id}",
                title=title,
                author=" ".join((author_a.text() or "").split()) if author_a else None,
                posted_at=parse_kr_datetime(date_txt),
                votes=parse_int(votes_td),
                comments=parse_int(comments_a.text() if comments_a else None),
            )
        )
    return posts
