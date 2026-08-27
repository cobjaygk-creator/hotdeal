from __future__ import annotations

from selectolax.parser import HTMLParser

from app.family import RawSale
from app.family.parse import extract_entry_code, is_family_title, parse_date_range
from app.http_client import PoliteClient


class EomisaeFamilySource:
    name = "eomisae"

    async def fetch_latest(self, client: PoliteClient) -> list[RawSale]:
        posts = await _board_posts(client)
        sales: list[RawSale] = []
        for post in posts:
            if not is_family_title(post.title):
                continue
            sale = RawSale(
                source_name="eomisae",
                source_post_id=post.source_post_id,
                title=post.title,
                source_url=post.url,
                date_range=post.title,
            )
            try:
                detail = await client.get(post.url)
            except Exception:
                sales.append(sale)
                continue
            if not detail.not_modified:
                enrich_from_detail(sale, detail.text)
            sales.append(sale)
        return sales


async def _board_posts(client: PoliteClient):
    from app.sources.eomisae import EomisaeSource

    return await EomisaeSource().fetch_latest(client)


def enrich_from_detail(sale: RawSale, html: str) -> None:
    tree = HTMLParser(html)
    body = tree.css_first(".xe_content") or tree.css_first("#content") or tree.body
    text = body.text() if body else ""
    sale.body = " ".join(text.split())[:4000]
    start, end = parse_date_range(sale.body)
    if start:
        sale.date_range = f"{start} ~ {end}"
    sale.entry_code = extract_entry_code(sale.body or "")
    for a in (body.css("a") if body else []):
        href = a.attributes.get("href") or ""
        if href.startswith("http") and "eomisae.co.kr" not in href:
            sale.deal_url = href
            break
    for row in tree.css("table tr"):
        cells = [ " ".join((c.text() or "").split()) for c in row.css("th, td") ]
        line = " ".join(cells)
        code = extract_entry_code(line)
        if code:
            sale.entry_code = code
        if "링크" in line:
            for a in row.css("a"):
                href = a.attributes.get("href") or ""
                if href.startswith("http"):
                    sale.deal_url = href
