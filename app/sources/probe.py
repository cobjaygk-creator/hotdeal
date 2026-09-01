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

    all_hrefs = [a.attributes.get("href") or "" for a in tree.css("a[href]")]
    script_srcs = [
        (s.attributes.get("src") or "")[:160]
        for s in tree.css("script[src]")
        if s.attributes.get("src")
    ][:30]
    api_like = sorted(
        {
            m.group(0)
            for m in re.finditer(
                r"https?://[^\"'\s]+(?:api|graphql|saleinfo|bbs)[^\"'\s]*",
                text,
                flags=re.I,
            )
        }
    )[:40]
    markers = {
        "__NEXT_DATA__": "__NEXT_DATA__" in text,
        "nuxt": "window.__NUXT__" in text or 'id="__nuxt"' in text,
        "vue": "data-v-" in text[:5000],
        "react": "data-reactroot" in text or "__NEXT_DATA__" in text,
        "login": "로그인" in text or "login" in text.lower(),
    }
    # Compact body text sample after stripping scripts/styles roughly.
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    body = " ".join(re.sub(r"(?is)<[^>]+>", " ", body).split())

    return {
        "source": name,
        "url": url,
        "status": result.status,
        "bytes": len(result.content),
        "blocked": blocked,
        "selector_counts": counts,
        "sample_hrefs": hrefs,
        "all_href_count": len(all_hrefs),
        "all_href_sample": all_hrefs[:30],
        "interesting_classes": class_hits.most_common(50),
        "script_srcs": script_srcs,
        "api_like": api_like,
        "markers": markers,
        "title": " ".join(((tree.css_first("title").text() if tree.css_first("title") else "") or "").split()),
        "head": " ".join(text[:300].split()),
        "body_sample": body[:800],
    }
