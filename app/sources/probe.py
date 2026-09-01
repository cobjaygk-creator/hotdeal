from __future__ import annotations

import re
from collections import Counter

from selectolax.parser import HTMLParser

from app.http_client import PoliteClient
from app.sources import arca, coolenjoy, damoang, quasarzone
from app.sources.html_fetch import block_reason

SOURCE_URLS = {
    "arca": arca.LIST_URL,
    "quasarzone": quasarzone.LIST_URL,
    "damoang": damoang.LIST_URL,
    "coolenjoy": coolenjoy.LIST_URL,
}

SELECTOR_PROBES = [
    "div.market-info-list",
    "a.subject-link",
    "div.market-info-list-cont",
    "div.list-item",
    "tr.list-item",
    "div.board-list",
    "ul.list-wrapper li",
    "div.tit",
    "table tbody tr",
    "a[href*='/bbs/qb_saleinfo/views/']",
    "a[href*='qb_saleinfo']",
]


async def probe_source(client: PoliteClient, name: str) -> dict:
    url = SOURCE_URLS.get(name)
    if not url:
        return {"error": f"unsupported probe source: {name}", "supported": sorted(SOURCE_URLS)}

    result = await client.get(url)
    blocked = block_reason(result)
    text = result.text or ""
    tree = HTMLParser(text)
    counts = {sel: len(tree.css(sel)) for sel in SELECTOR_PROBES}

    hrefs: list[str] = []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if "views" in href or "qb_saleinfo" in href:
            title = " ".join((a.text() or "").split())[:80]
            hrefs.append(f"{href} | {title}")
            if len(hrefs) >= 25:
                break

    class_hits: Counter[str] = Counter()
    for m in re.finditer(r'class="([^"]+)"', text):
        for part in m.group(1).split():
            low = part.lower()
            if any(k in low for k in ("market", "subject", "sale", "list", "board", "item", "tit", "deal")):
                class_hits[part] += 1

    return {
        "source": name,
        "url": url,
        "status": result.status,
        "bytes": len(result.content),
        "blocked": blocked,
        "selector_counts": counts,
        "sample_hrefs": hrefs,
        "interesting_classes": class_hits.most_common(50),
        "head": " ".join(text[:300].split()),
    }
