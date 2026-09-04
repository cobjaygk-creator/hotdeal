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
SKIP_TITLES = ("이용 규정", "상품권 이벤트", "list_adsense", "list_ad_link")


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

    # Card layout (has list thumbnails).
    for card in tree.css("div.card_el"):
        link = None
        for a in card.css("a.pjax"):
            href = (a.attributes.get("href") or "").split("#")[0]
            if re.fullmatch(r"/(fs|rt|os)/\d+", href):
                link = a
                break
        if not link:
            continue
        post = _post_from_link(link, card)
        if not post or post.source_post_id in seen:
            continue
        if any(skip in (post.title or "") for skip in SKIP_TITLES):
            continue
        seen.add(post.source_post_id)
        posts.append(post)

    # Table / plain list fallback.
    for link in tree.css("a.pjax"):
        href = (link.attributes.get("href") or "").split("#")[0]
        if not re.fullmatch(r"/(fs|rt|os)/\d+", href):
            continue
        post_id = href.rsplit("/", 1)[-1]
        if post_id in seen:
            continue
        row = link.parent
        while row and row.tag != "tr":
            row = row.parent
        post = _post_from_link(link, row)
        if not post:
            continue
        if any(skip in (post.title or "") for skip in SKIP_TITLES):
            continue
        cate = row.css_first("span.cate") if row else None
        cate_txt = " ".join((cate.text() or "").split()) if cate else ""
        if any(skip in cate_txt for skip in ("공지", "AD", "광고")):
            continue
        seen.add(post.source_post_id)
        posts.append(post)
    return posts


def _post_from_link(link, root) -> RawPost | None:
    href = (link.attributes.get("href") or "").split("#")[0]
    m = re.fullmatch(r"/(fs|rt|os)/(\d+)", href)
    if not m:
        return None
    board, post_id = m.group(1), m.group(2)
    title = " ".join((link.text() or "").split())
    if not title or title.isdigit():
        return None
    author = None
    posted_at = None
    votes = 0
    comments = 0
    if root is not None:
        author_a = root.css_first("a[href='#popup_menu_area']")
        if author_a:
            author = " ".join((author_a.text() or "").split()) or None
        comments_a = root.css_first("a.tt_cm")
        comments = parse_int(comments_a.text() if comments_a else None)
        if root.tag == "tr":
            tds = root.css("td")
            date_txt = tds[-2].text() if len(tds) >= 2 else None
            votes = parse_int(tds[-1].text() if tds else None)
            posted_at = parse_kr_datetime(date_txt)
        else:
            # Card date sits in a <span> near the category.
            for span in root.css("div.card_content p span"):
                txt = " ".join((span.text() or "").split())
                if re.match(r"\d{2}\.\d{2}\.\d{2}", txt):
                    posted_at = parse_kr_datetime(txt)
                    break
    thumb = _thumb(root)
    extra = {"thumbnail_url": thumb} if thumb else {}
    return RawPost(
        source="eomisae",
        source_post_id=post_id,
        url=f"https://eomisae.co.kr/{board}/{post_id}",
        title=title,
        author=author,
        posted_at=posted_at,
        votes=votes,
        comments=comments,
        extra=extra,
    )


def _thumb(root) -> str | None:
    if root is None:
        return None
    img = root.css_first("img.tmb[src]") or root.css_first("img[src*='thumbnails']")
    if not img:
        return None
    src = (img.attributes.get("src") or "").strip()
    if not src or src.startswith("data:"):
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://eomisae.co.kr" + src
    return src
