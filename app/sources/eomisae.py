from __future__ import annotations

import email.utils
import re
from xml.etree import ElementTree as ET

from app.http_client import PoliteClient
from app.sources import RawPost
from app.sources.html_fetch import fetch_parsed

# Combined RSS for all boards; filter to deal boards by URL path.
RSS_URL = "https://eomisae.co.kr/rss"
LIST_URL = RSS_URL  # kept for the debug probe
# Keep only deal boards: fs (인기정보) and rt (기타정보/추천 핫딜)
_DEAL_BOARDS = re.compile(r"https://eomisae\.co\.kr/(fs|rt)/(\d+)")
SKIP_TITLES = ("이용 규정", "상품권 이벤트")
_IMG_RE = re.compile(r"""<img[^>]+src\s*=\s*["']([^"']+)["']""", re.I)


class EomisaeSource:
    name = "eomisae"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        return await fetch_parsed(
            client, RSS_URL, parse_rss, timeout=20.0, max_retries=1, curl_fallback=False
        )


def parse_rss(xml_text: str) -> list[RawPost]:
    root = ET.fromstring(xml_text)
    posts: list[RawPost] = []
    seen: set[str] = set()
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        m = _DEAL_BOARDS.match(link)
        if not m:
            continue
        board, post_id = m.group(1), m.group(2)
        if post_id in seen:
            continue
        title = " ".join((item.findtext("title") or "").split())
        if not title or any(skip in title for skip in SKIP_TITLES):
            continue
        seen.add(post_id)
        desc = (item.findtext("description") or "").strip() or None
        # dc:creator
        author = None
        for child in item:
            if child.tag.endswith("}creator") or child.tag == "dc:creator":
                author = (child.text or "").strip() or None
                break
        posted = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                posted = email.utils.parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted = None
        cats = [c.text.strip() for c in item if c.tag == "category" and c.text]
        extra: dict = {}
        thumb = _first_thumb(desc)
        if thumb:
            extra["thumbnail_url"] = thumb
        if cats:
            extra["source_category"] = "/".join(cats)
        posts.append(
            RawPost(
                source="eomisae",
                source_post_id=post_id,
                url=f"https://eomisae.co.kr/{board}/{post_id}",
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
            return "https://eomisae.co.kr" + src
        if src.startswith("http"):
            return src
    return None
