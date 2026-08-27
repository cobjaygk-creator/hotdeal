from __future__ import annotations

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.util.timeparse import parse_int, parse_kr_datetime

LIST_URL = "https://quasarzone.com/bbs/qb_saleinfo"


class QuasarzoneSource:
    name = "quasarzone"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        result = await client.get(LIST_URL)
        if result.not_modified:
            return []
        return parse_list(result.text)


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    seen: set[str] = set()
    for item in tree.css("div.market-info-list"):
        link = item.css_first("a.subject-link")
        if not link:
            continue
        href = link.attributes.get("href") or ""
        post_id = _id_from_href(href)
        if not post_id or post_id in seen:
            continue
        label = item.css_first("span.label")
        if label and "공지" in (label.text() or ""):
            continue
        seen.add(post_id)
        title = " ".join((link.text() or "").split())
        price_el = item.css_first("span.text-orange")
        brand_el = item.css_first("span.brand")
        seller = " ".join((brand_el.text() or "").split()) if brand_el else None
        if price_el:
            price_txt = " ".join((price_el.text() or "").split())
            if price_txt and "(" not in title:
                title = f"{title} ({price_txt})"
        if seller and not title.startswith("["):
            title = f"[{seller}] {title}"
        nick = item.css_first("[data-nick]")
        comments = item.css_first("span.ctn-count")
        views = item.css_first("span.count")
        date_el = item.css_first("span.date")
        posts.append(
            RawPost(
                source="quasarzone",
                source_post_id=post_id,
                url=f"https://quasarzone.com/bbs/qb_saleinfo/views/{post_id}",
                title=title,
                author=nick.attributes.get("data-nick") if nick else None,
                posted_at=parse_kr_datetime(date_el.text() if date_el else None),
                views=parse_int(views.text() if views else None),
                comments=parse_int(comments.text() if comments else None),
            )
        )
    return posts


def _id_from_href(href: str) -> str | None:
    parts = href.split("?")[0].rstrip("/").split("/")
    if "views" in parts:
        idx = parts.index("views")
        if idx + 1 < len(parts) and parts[idx + 1].isdigit():
            return parts[idx + 1]
    return next((p for p in reversed(parts) if p.isdigit()), None)
