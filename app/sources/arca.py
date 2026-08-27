from __future__ import annotations

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import RawPost
from app.util.timeparse import parse_int, parse_iso

LIST_URL = "https://arca.live/b/hotdeal"


class ArcaSource:
    name = "arca"

    async def fetch_latest(self, client: PoliteClient) -> list[RawPost]:
        result = await client.get(LIST_URL)
        if result.not_modified:
            return []
        return parse_list(result.text)


def parse_list(html: str) -> list[RawPost]:
    tree = HTMLParser(html)
    posts: list[RawPost] = []
    seen: set[str] = set()
    for row in tree.css("div.vrow.hybrid"):
        title_a = row.css_first("a.title.hybrid-title")
        if not title_a:
            continue
        href = title_a.attributes.get("href") or ""
        post_id = _id_from_href(href)
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)
        title = " ".join((title_a.text() or "").split())
        price_el = row.css_first("span.deal-price")
        delivery_el = row.css_first("span.deal-delivery")
        extra_bits = []
        if price_el:
            extra_bits.append((price_el.text() or "").strip())
        if delivery_el:
            extra_bits.append((delivery_el.text() or "").strip())
        if extra_bits and "(" not in title:
            title = f"{title} ({' / '.join(extra_bits)})"
        author_el = row.css_first("span[data-filter]")
        time_el = row.css_first("time[datetime]")
        views_el = row.css_first("span.col-view")
        rate_el = row.css_first("span.col-rate")
        posts.append(
            RawPost(
                source="arca",
                source_post_id=post_id,
                url=f"https://arca.live/b/hotdeal/{post_id}",
                title=title,
                author=author_el.attributes.get("data-filter") if author_el else None,
                posted_at=parse_iso(time_el.attributes.get("datetime") if time_el else None),
                votes=parse_int(rate_el.text() if rate_el else None),
                views=parse_int(views_el.text() if views_el else None),
            )
        )
    return posts


def _id_from_href(href: str) -> str | None:
    for part in href.split("?")[0].rstrip("/").split("/"):
        if part.isdigit():
            return part
    return None
