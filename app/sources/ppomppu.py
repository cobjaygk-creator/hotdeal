from __future__ import annotations

import email.utils
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.util.timeparse import parse_int, parse_kr_datetime

RSS_URL = "https://www.ppomppu.co.kr/rss.php?id=ppomppu"
LIST_URL = "https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu"


class PpomppuSource:
    name = "ppomppu"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        result = await client.get(RSS_URL)
        if result.not_modified:
            return []
        return parse_rss(result.text)

    async def fetch_page(self, client: PoliteClient, page: int) -> list[RawPost]:
        url = LIST_URL if page <= 1 else f"{LIST_URL}&page={page}"
        result = await client.get(url, encoding="euc-kr")
        if result.not_modified:
            return []
        return parse_list_html(result.text)


def parse_rss(xml_text: str) -> list[RawPost]:
    root = ET.fromstring(xml_text)
    posts: list[RawPost] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        author = (item.findtext("author") or "").strip() or None
        pub = item.findtext("pubDate")
        posted = None
        if pub:
            try:
                posted = email.utils.parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted = None
        post_id = _id_from_url(link)
        if not post_id or not title:
            continue
        hits = (item.findtext("hits") or "").strip()
        votes, views = _hits(hits)
        posts.append(
            RawPost(
                source="ppomppu",
                source_post_id=post_id,
                url=_canonical(post_id),
                title=title,
                body=desc or None,
                author=author,
                posted_at=posted,
                votes=votes,
                views=views,
            )
        )
    return posts


def parse_list_html(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    for row in tree.css("tr.baseList"):
        numb = row.css_first("td.baseList-numb")
        title_a = row.css_first("a.baseList-title")
        if not numb or not title_a:
            continue
        post_id = (numb.text() or "").strip()
        if not post_id.isdigit():
            continue
        title = " ".join((title_a.text() or "").split())
        time_td = row.css_first("td[title]")
        posted = None
        if time_td:
            posted = parse_kr_datetime(time_td.attributes.get("title"))
        author_el = row.css_first("span.baseList-name")
        rec = row.css_first("td.baseList-rec")
        views_el = row.css_first("td.baseList-views")
        comments_el = row.css_first("span.baseList-c")
        rec_text = rec.text() if rec else ""
        votes = parse_int(rec_text.split("-")[0] if rec_text else "0")
        posts.append(
            RawPost(
                source="ppomppu",
                source_post_id=post_id,
                url=_canonical(post_id),
                title=title,
                author=(author_el.text() if author_el else None),
                posted_at=posted,
                votes=votes,
                views=parse_int(views_el.text() if views_el else None),
                comments=parse_int(comments_el.text() if comments_el else None),
            )
        )
    return posts


def _id_from_url(url: str) -> str | None:
    qs = parse_qs(urlparse(url).query)
    nos = qs.get("no")
    return nos[0] if nos else None


def _canonical(post_id: str) -> str:
    return f"https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no={post_id}"


def _hits(raw: str) -> tuple[int, int]:
    # e.g. [0|89|0|0]
    parts = [p for p in raw.replace("[", "").replace("]", "").split("|") if p]
    if len(parts) >= 2:
        return parse_int(parts[0]), parse_int(parts[1])
    return 0, parse_int(raw)
