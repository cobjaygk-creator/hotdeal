from __future__ import annotations

import email.utils
import re
from xml.etree import ElementTree as ET

import httpx

from app.config import PPOMPPU_PROXY_URL, USER_AGENT
from app.http_client import PoliteClient
from app.sources import RawPost

# The board HTML repeatedly ReadTimeout'd from the cloud host; the RSS feed is
# small, fast, and carries the post body (with images) inline.
RSS_URL = "https://coolenjoy.net/bbs/rss.php?bo_table=jirum"
LIST_URL = RSS_URL  # kept for the debug probe
_ID_RE = re.compile(r"/bbs/jirum/(\d+)")
_IMG_RE = re.compile(r"""<img[^>]+src\s*=\s*["']([^"']+)["']""", re.I)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://coolenjoy.net/",
}


class CoolenjoySource:
    name = "coolenjoy"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        # Bypass PoliteClient to avoid Chrome TLS impersonation overhead that
        # pushes total latency past the 120s collection budget.
        # Try KR proxy first (Korean ISP → Korean site = fast), then direct.
        # 50s × 2 paths = 100s max, within the 120s budget.
        proxies: list[str | None] = []
        if PPOMPPU_PROXY_URL:
            proxies.append(PPOMPPU_PROXY_URL)
        proxies.append(None)  # direct fallback always present

        last_exc: Exception | None = None
        for proxy in proxies:
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=50.0,
                    proxy=proxy,
                    headers=_HEADERS,
                ) as http:
                    resp = await http.get(RSS_URL)
                    resp.raise_for_status()
                posts = parse_rss(resp.text)
                if posts:
                    return posts
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise last_exc or RuntimeError(f"parsed 0 posts from coolenjoy RSS ({RSS_URL})")


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
        if not title or "공지" in title:
            continue
        seen.add(post_id)
        desc = (item.findtext("description") or "").strip() or None
        author = (item.findtext("author") or "").strip() or None
        posted = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                posted = email.utils.parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted = None
        extra: dict = {}
        thumb = _first_thumb(desc)
        if thumb:
            extra["thumbnail_url"] = thumb
        cat = (item.findtext("category") or "").strip()
        if cat and cat.lower() not in ("jirum", "지름"):
            extra["source_category"] = cat
        posts.append(
            RawPost(
                source="coolenjoy",
                source_post_id=post_id,
                url=f"https://coolenjoy.net/bbs/jirum/{post_id}",
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
            return "https://coolenjoy.net" + src
        if src.startswith("http"):
            return src
    return None
