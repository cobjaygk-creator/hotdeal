from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from app.family import RawSale
from app.http_client import PoliteClient

from app.family.parse import CAT_MAP

LIST_URL = "https://dealink.co.kr/familysale"
ID_RE = re.compile(r"/familysale/(\d+)")

# 앞쪽 페이지일수록 진행중·예정 세일. 뒤로 갈수록 종료분이라 3페이지면 충분.
PAGES = 3


class DealinkSource:
    name = "dealink"

    async def fetch_latest(self, client: PoliteClient) -> list[RawSale]:
        out: list[RawSale] = []
        seen: set[str] = set()
        for page in range(1, PAGES + 1):
            url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
            try:
                result = await client.get(url)
            except Exception:
                break
            if result.not_modified:
                continue
            page_sales = parse_list(result.text)
            if not page_sales:
                break
            for sale in page_sales:
                if sale.source_post_id in seen:
                    continue
                seen.add(sale.source_post_id)
                out.append(sale)
        return out


def parse_list(html: str) -> list[RawSale]:
    tree = HTMLParser(html)
    sales: list[RawSale] = []
    seen: set[str] = set()
    for card in tree.css("div.swiper-slide-familysale"):
        link = card.css_first("ul.gallery-item-tit a")
        if not link:
            continue
        href = link.attributes.get("href") or ""
        m = ID_RE.search(href)
        if not m:
            continue
        post_id = m.group(1)
        if post_id in seen:
            continue
        title = " ".join((link.text() or "").split())
        if not title:
            continue
        info = card.css_first("ul.gallery-item-info")
        info_txt = " ".join((info.text() or "").split()) if info else ""
        category = None
        for name in list(CAT_MAP) + ["브랜드데이"]:
            if name in info_txt:
                category = name
                break
        date_el = card.css_first("ul.gallery-item-date")
        hint_el = card.css_first("ul.gallery-item-con")
        labels = [ " ".join((s.text() or "").split()) for s in card.css(".bbs_list_label, .main_rb_bg") ]
        img_el = card.css_first("ul.gallery-item-img img[src]")
        thumb = (img_el.attributes.get("src") or "").strip() if img_el else None
        if thumb and thumb.startswith("/"):
            thumb = "https://dealink.co.kr" + thumb
        if thumb and not thumb.startswith("http"):
            thumb = None
        seen.add(post_id)
        sales.append(
            RawSale(
                source_name="dealink",
                source_post_id=post_id,
                title=title,
                source_url=f"https://dealink.co.kr/familysale/{post_id}",
                category_raw=category,
                date_range=" ".join((date_el.text() or "").split()) if date_el else None,
                discount_hint=" ".join((hint_el.text() or "").split()) if hint_el else None,
                labels=[x for x in labels if x],
                thumbnail_url=thumb,
            )
        )
    return sales
