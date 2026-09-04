from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.util.timeparse import parse_int, parse_kr_datetime

BOARDS = (
    "deal_domestic",
    "deal_oversea",
)


class DealbadaSource:
    name = "dealbada"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        posts: list[RawPost] = []
        seen: set[str] = set()
        for board in BOARDS:
            url = f"https://www.dealbada.com/bbs/board.php?bo_table={board}"
            result = await client.get(url)
            if result.not_modified:
                continue
            for post in parse_list(result.text, board):
                key = f"{board}:{post.source_post_id}"
                if key in seen:
                    continue
                seen.add(key)
                post.source_post_id = key
                posts.append(post)
        return posts


def parse_list(html: str, board: str = "deal_domestic") -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    for row in tree.css("td.td_subject"):
        link = None
        for a in row.css("a"):
            href = a.attributes.get("href") or ""
            if "wr_id=" in href:
                link = a
                break
        if not link:
            continue
        href = (link.attributes.get("href") or "").replace("&amp;", "&")
        if f"bo_table={board}" not in href:
            continue
        wr_id = _wr_id(href)
        if not wr_id:
            continue
        title = " ".join((link.text() or "").split())
        title = title.replace("댓글", "").strip()
        title = re.sub(r"^딜바다\s*::\s*", "", title, flags=re.I)
        title = re.sub(r"\s*>\s*(국내핫딜|해외핫딜|기타정보|인기정보)\s*$", "", title)
        if not title or title.startswith("[공지]") or "이용안내" in title:
            continue
        tr = row.parent
        author_el = tr.css_first("div.div_nickname") if tr else None
        date_el = tr.css_first("td.td_date") if tr else None
        views_el = tr.css_first("td.td_num") if tr else None
        vote_el = tr.css_first("td.td_num_g") if tr else None
        thumb = _thumb(tr)
        extra = {"thumbnail_url": thumb} if thumb else {}
        posts.append(
            RawPost(
                source="dealbada",
                source_post_id=wr_id,
                url=f"https://www.dealbada.com/bbs/board.php?bo_table={board}&wr_id={wr_id}",
                title=title,
                author=" ".join((author_el.text() or "").split()) if author_el else None,
                posted_at=parse_kr_datetime(date_el.text() if date_el else None),
                votes=parse_int(vote_el.text().split("/")[0] if vote_el else None),
                views=parse_int(views_el.text() if views_el else None),
                extra=extra,
            )
        )
    return posts


def _thumb(tr) -> str | None:
    if tr is None:
        return None
    img = tr.css_first("td.td_img img[src]")
    if not img:
        return None
    src = (img.attributes.get("src") or "").strip()
    if not src or src.startswith("data:") or "thumb_up.png" in src:
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http://"):
        return "https://" + src[len("http://") :]
    if src.startswith("/"):
        return "https://www.dealbada.com" + src
    return src


def _wr_id(href: str) -> str | None:
    if href.startswith("//"):
        href = "https:" + href
    qs = parse_qs(urlparse(href).query)
    ids = qs.get("wr_id")
    return ids[0] if ids else None
