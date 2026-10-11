from __future__ import annotations

import asyncio
import re
import logging
from urllib.parse import parse_qs, urlparse

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient, soft_block_reason
from app.config import PPOMPPU_PROXY_URL
from app.sources import RawPost
from app.util.timeparse import parse_int, parse_kr_datetime

BOARDS = (
    "deal_domestic",
    "deal_oversea",
)
log = logging.getLogger(__name__)
# Two boards use at most 2 * (6 + 16) = 44 seconds of request budget,
# leaving headroom inside the collector's 60-second source deadline.
DIRECT_BUDGET_SECONDS = 6.0
PROXY_BUDGET_SECONDS = 16.0


async def _fetch_board(client, url, *, proxy=None):
    budget = PROXY_BUDGET_SECONDS if proxy else DIRECT_BUDGET_SECONDS
    # Covers host-lock waiting, backoff, TLS impersonation and fallback too.
    async with asyncio.timeout(budget):
        result = await client.get(
            url, proxy=proxy, timeout=budget, max_retries=1, curl_fallback=False
        )
    if not result.not_modified:
        if result.status != 200:
            raise RuntimeError(f"HTTP {result.status}")
        if reason := soft_block_reason(result.text):
            raise RuntimeError(f"blocked response: {reason}")
    return result


class DealbadaSource:
    name = "dealbada"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        posts: list[RawPost] = []
        seen: set[str] = set()
        failures: list[str] = []
        for board in BOARDS:
            url = f"https://www.dealbada.com/bbs/board.php?bo_table={board}"
            try:
                result = await _fetch_board(client, url)
            except Exception as direct_error:  # noqa: BLE001 - try the configured KR exit
                if not PPOMPPU_PROXY_URL:
                    failure = f"{board}: direct={type(direct_error).__name__}; proxy=disabled"
                    failures.append(failure)
                    log.warning("dealbada %s", failure)
                    continue
                try:
                    result = await _fetch_board(client, url, proxy=PPOMPPU_PROXY_URL)
                    log.info("dealbada %s recovered through configured proxy", board)
                except Exception as proxy_error:  # noqa: BLE001 - preserve other board
                    failure = (
                        f"{board}: direct={type(direct_error).__name__}; "
                        f"proxy={type(proxy_error).__name__}"
                    )
                    failures.append(failure)
                    log.warning("dealbada %s", failure)
                    continue
            if result.not_modified:
                continue
            for post in parse_list(result.text, board):
                key = f"{board}:{post.source_post_id}"
                if key in seen:
                    continue
                seen.add(key)
                post.source_post_id = key
                posts.append(post)
        if len(failures) == len(BOARDS):
            raise RuntimeError("all dealbada boards failed: " + " | ".join(failures))
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
