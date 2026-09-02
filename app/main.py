from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import (
    ADMIN_PASSWORD,
    COLLECT_INTERVAL_MINUTES,
    ENABLE_COLLECT,
    FAMILY_SALE_INTERVAL_MINUTES,
    PPOMPPU_INTERVAL_SECONDS,
    SITE_URL,
)
from app.db import connect, get_meta, upsert_family_sale, utcnow_iso
from app.engine.alerts import add_sub, channels_ready, default_target, delete_sub, list_subs
from app.family.parse import parse_discount
from app.family.pipeline import collect_family_sales
from app.family.query import CATEGORIES, get_sale, list_sales, month_grid, parse_cats, parse_year_month
from app.events import EventHub
from app.http_client import PoliteClient
from app.pipeline import collect_and_process
from app.sources.registry import SOURCE_LABELS, get_sources
from app.util.timeparse import format_kst, format_relative

log = logging.getLogger("hotdeal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["kst"] = format_kst
TEMPLATES.env.filters["reltime"] = format_relative
TEMPLATES.env.globals["site_url"] = SITE_URL
TEMPLATES.env.globals["website_jsonld"] = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "Organization", "name": "핫딜모음", "url": SITE_URL},
        {
            "@type": "WebSite",
            "name": "핫딜모음",
            "url": SITE_URL,
            "potentialAction": {
                "@type": "SearchAction",
                "target": SITE_URL + "/search?q={search_term_string}",
                "query-input": "required name=search_term_string",
            },
        },
    ],
}
STATIC_DIR = Path(__file__).parent / "static"
PAGE_SIZE = 40

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["db"] = await connect()
    state["http"] = PoliteClient()
    state["hub"] = EventHub()
    state["collect_lock"] = asyncio.Lock()
    scheduler = None
    if ENABLE_COLLECT:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _scheduled_collect,
            "interval",
            seconds=PPOMPPU_INTERVAL_SECONDS,
            id="collect_ppomppu",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=20),
        )
        scheduler.add_job(
            _scheduled_collect_others,
            "interval",
            minutes=COLLECT_INTERVAL_MINUTES,
            id="collect_others",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=15),
        )
        scheduler.add_job(
            _scheduled_family,
            "interval",
            minutes=FAMILY_SALE_INTERVAL_MINUTES,
            id="collect_family",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=25),
        )
        scheduler.start()
        log.info("scheduled collect enabled")
    else:
        log.info("scheduled collect disabled (set ENABLE_COLLECT=1 to crawl from this machine)")
    state["scheduler"] = scheduler
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await state["http"].aclose()
        await state["db"].close()


app = FastAPI(title="자동 핫딜 탐지기", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


async def _scheduled_collect() -> None:
    await _run_collect(["ppomppu"])


async def _scheduled_collect_others() -> None:
    await _run_collect(
        [
            "arca",
            "quasarzone",
            "clien",
            "ruliweb",
            "damoang",
            "coolenjoy",
            "eomisae",
            "dealbada",
        ]
    )


async def _scheduled_family() -> None:
    async with state["collect_lock"]:
        try:
            await collect_family_sales(state["db"], state["http"])
        except Exception:
            log.exception("family collect failed")


async def _run_collect(names: list[str] | None) -> dict:
    async with state["collect_lock"]:
        try:
            summary = await collect_and_process(state["db"], get_sources(names), state["http"])
        except Exception:
            log.exception("scheduled collect failed")
            return {"errors": ["collect failed"], "new_deals": [], "sources": {}}
        stats = await _stats()
        state["hub"].publish(
            {
                "type": "tick",
                "stats": stats,
                "sources": summary.get("sources") or {},
                "new_posts": summary.get("new_posts") or 0,
                "items": summary.get("new_deals") or [],
            }
        )
        return summary


def _db():
    return state["db"]


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    grade: str | None = None,
    seller: str | None = None,
    source: str | None = None,
    cat: str | None = None,
):
    stats = await _stats()
    category = cat if cat in DEAL_CATEGORIES else ""
    deals = await _list_deals(grade=grade, seller=seller, source=None, category=category or None, limit=PAGE_SIZE)
    sellers = await _distinct("seller")
    sources = await _distinct_sources()
    ordered_sources = [s.name for s in get_sources() if s.name in set(sources)]
    for name in sources:
        if name not in ordered_sources:
            ordered_sources.append(name)
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "deals": deals,
            "grade": grade or "",
            "seller": seller or "",
            "source": source or "",
            "category": category,
            "categories": DEAL_CATEGORIES,
            "sellers": sellers,
            "sources": ordered_sources,
            "source_labels": SOURCE_LABELS,
            "page_size": PAGE_SIZE,
            "has_more": len(deals) >= PAGE_SIZE,
            "nav": "hotdeal",
        },
    )


@app.get("/family", response_class=HTMLResponse)
async def family_index(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    day: str | None = None,
    cat: list[str] | None = Query(None),
    code: str | None = None,
):
    cats = parse_cats(cat or [])
    entry_only = code == "1"
    y, m = parse_year_month(year, month)
    sales = await list_sales(_db(), categories=cats, entry_only=entry_only, include_ended=True)
    live = [s for s in sales if s["status"] in ("진행중", "예정")]
    grid = month_grid(y, m, sales)
    if m == 1:
        prev = {"year": y - 1, "month": 12}
    else:
        prev = {"year": y, "month": m - 1}
    if m == 12:
        nxt = {"year": y + 1, "month": 1}
    else:
        nxt = {"year": y, "month": m + 1}
    if day:
        day_sales = [
            s
            for s in sales
            if s.get("start_date") and s.get("end_date") and s["start_date"][:10] <= day <= s["end_date"][:10]
        ]
        if entry_only:
            day_sales = [s for s in day_sales if s.get("has_entry_code")]
        if cats:
            day_sales = [s for s in day_sales if set(s.get("categories") or []) & set(cats)]
    else:
        day_sales = live
    last = await get_meta(_db(), "last_family_collect_at")
    stats = {
        "live": sum(1 for s in live if s["status"] == "진행중"),
        "upcoming": sum(1 for s in live if s["status"] == "예정"),
        "codes": sum(1 for s in live if s.get("has_entry_code")),
        "last": last,
    }
    return TEMPLATES.TemplateResponse(
        "family.html",
        {
            "request": request,
            "nav": "family",
            "grid": grid,
            "prev": prev,
            "next": nxt,
            "sales": sales,
            "day_sales": day_sales,
            "selected": day or "",
            "cats": cats,
            "all_cats": CATEGORIES,
            "entry_only": entry_only,
            "stats": stats,
        },
    )


@app.get("/family/admin", response_class=HTMLResponse)
async def family_admin(request: Request):
    return TEMPLATES.TemplateResponse(
        "family_admin.html",
        {
            "request": request,
            "nav": "family",
            "authed": _is_admin(request),
            "all_cats": CATEGORIES,
            "error": None,
        },
    )


@app.post("/family/admin")
async def family_admin_post(
    request: Request,
    action: str = Form(...),
    password: str | None = Form(None),
    brand_names: str | None = Form(None),
    title: str | None = Form(None),
    sale_type: str | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    location: str | None = Form(None),
    entry_code: str | None = Form(None),
    category: str | None = Form(None),
    discount_label: str | None = Form(None),
    source_url: str | None = Form(None),
):
    if action == "login":
        if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
            resp = RedirectResponse("/family/admin", status_code=303)
            resp.set_cookie("family_admin", _admin_token(), httponly=True, samesite="lax")
            return resp
        return TEMPLATES.TemplateResponse(
            "family_admin.html",
            {
                "request": request,
                "nav": "family",
                "authed": False,
                "all_cats": CATEGORIES,
                "error": "비밀번호가 없거나 틀립니다.",
            },
            status_code=401,
        )
    if not _is_admin(request):
        return RedirectResponse("/family/admin", status_code=303)
    brands = [b.strip() for b in (brand_names or "").split(",") if b.strip()]
    label, mx = parse_discount(title or "", discount_label)
    sale = {
        "source_name": "manual",
        "source_post_id": f"m-{utcnow_iso().replace(' ', '').replace(':', '')}",
        "title": title or " ".join(brands),
        "brand_names": brands,
        "sale_type": sale_type or "온라인",
        "sale_kind": None,
        "start_date": start_date,
        "end_date": end_date,
        "location": location or None,
        "has_entry_code": bool(entry_code),
        "entry_code": entry_code or None,
        "categories": [category] if category else ["기타"],
        "discount_label": discount_label or label,
        "discount_max": mx,
        "source_url": source_url,
    }
    await upsert_family_sale(_db(), sale)
    await _db().commit()
    from app.family.pipeline import merge_family_groups

    await merge_family_groups(_db())
    await _db().commit()
    return RedirectResponse("/family", status_code=303)


@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    subs = await list_subs(_db()) if _is_admin(request) else []
    return TEMPLATES.TemplateResponse(
        "alerts.html",
        {
            "request": request,
            "nav": "alerts",
            "authed": _is_admin(request),
            "subs": [_public_sub(s) for s in subs],
            "ready": channels_ready(),
            "error": None,
        },
    )


def _public_sub(sub: dict) -> dict:
    target = sub.get("target") or ""
    if sub.get("channel") == "discord":
        masked = "웹훅 등록됨"
    elif len(target) > 8:
        masked = target[:2] + "…" + target[-4:]
    else:
        masked = "등록됨"
    return {**sub, "target_label": masked}


@app.post("/alerts")
async def alerts_post(
    request: Request,
    action: str = Form(...),
    password: str | None = Form(None),
    keyword: str | None = Form(None),
    min_grade: str | None = Form(None),
    channel: str | None = Form(None),
    target: str | None = Form(None),
    sub_id: int | None = Form(None),
):
    if action == "login":
        if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
            resp = RedirectResponse("/alerts", status_code=303)
            resp.set_cookie("family_admin", _admin_token(), httponly=True, samesite="lax")
            return resp
        return TEMPLATES.TemplateResponse(
            "alerts.html",
            {
                "request": request,
                "nav": "alerts",
                "authed": False,
                "subs": [],
                "ready": channels_ready(),
                "error": "비밀번호가 없거나 틀립니다.",
            },
            status_code=401,
        )
    if not _is_admin(request):
        return RedirectResponse("/alerts", status_code=303)
    if action == "delete" and sub_id:
        await delete_sub(_db(), sub_id)
        await _db().commit()
        return RedirectResponse("/alerts", status_code=303)
    if action == "create":
        ch = (channel or "").strip().lower()
        dest = (target or "").strip() or default_target(ch)
        try:
            await add_sub(_db(), keyword=keyword or "", min_grade=min_grade or "핫딜", channel=ch, target=dest)
            await _db().commit()
        except Exception:
            subs = await list_subs(_db())
            return TEMPLATES.TemplateResponse(
                "alerts.html",
                {
                    "request": request,
                    "nav": "alerts",
                    "authed": True,
                    "subs": [_public_sub(s) for s in subs],
                    "ready": channels_ready(),
                    "error": "키워드와 채널을 확인하고, Railway에 토큰/웹훅이 있는지 보세요.",
                },
                status_code=400,
            )
    return RedirectResponse("/alerts", status_code=303)


@app.get("/family/{sale_id}", response_class=HTMLResponse)
async def family_detail(request: Request, sale_id: int):
    sale = await get_sale(_db(), sale_id)
    if not sale:
        raise HTTPException(404, "sale not found")
    return TEMPLATES.TemplateResponse(
        "family_detail.html",
        {"request": request, "nav": "family", "sale": sale},
    )


def _require_collect() -> None:
    if not ENABLE_COLLECT:
        raise HTTPException(403, "collect disabled on this instance")


@app.post("/api/family/collect")
async def api_family_collect():
    _require_collect()
    async with state["collect_lock"]:
        summary = await collect_family_sales(state["db"], state["http"])
    return JSONResponse(summary)


def _admin_token() -> str:
    return sha256(f"family-admin:{ADMIN_PASSWORD}".encode()).hexdigest()


def _is_admin(request: Request) -> bool:
    return bool(ADMIN_PASSWORD) and request.cookies.get("family_admin") == _admin_token()


@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def deal_detail(request: Request, deal_id: int):
    deal = await _get_deal(deal_id)
    if not deal:
        raise HTTPException(404, "deal not found")
    posts = await _deal_posts(deal_id)
    history = await _price_history(deal["product_key"])
    return TEMPLATES.TemplateResponse(
        "deal.html",
        {
            "request": request,
            "nav": "hotdeal",
            "deal": deal,
            "posts": posts,
            "history": history,
            "jsonld": _deal_jsonld(deal),
        },
    )


@app.get("/api/deals")
async def api_deals(
    grade: str | None = None,
    seller: str | None = None,
    source: str | None = None,
    cat: str | None = None,
    ids: str | None = None,
    limit: int = Query(PAGE_SIZE, le=500),
    before_id: int | None = None,
):
    category = cat if cat in DEAL_CATEGORIES else None
    id_list = _parse_ids(ids)
    return await _list_deals(
        grade=grade,
        seller=seller,
        source=source,
        category=category,
        ids=id_list,
        limit=limit,
        before_id=None if id_list else before_id,
    )


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = ""):
    q = (q or "").strip()
    deals = await _search_deals(q, limit=50) if q else []
    return TEMPLATES.TemplateResponse(
        "search.html",
        {
            "request": request,
            "nav": "hotdeal",
            "q": q,
            "deals": deals,
            "source_labels": SOURCE_LABELS,
        },
    )


@app.get("/robots.txt")
async def robots():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /family/admin\n"
        "Disallow: /alerts\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@app.get("/sitemap.xml")
async def sitemap():
    cur = await _db().execute(
        "SELECT id FROM deals ORDER BY COALESCE(last_scored_at, last_seen_at) DESC LIMIT 400"
    )
    rows = await cur.fetchall()
    chunks = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"<url><loc>{SITE_URL}/</loc><changefreq>hourly</changefreq></url>",
        f"<url><loc>{SITE_URL}/family</loc><changefreq>daily</changefreq></url>",
        f"<url><loc>{SITE_URL}/search</loc><changefreq>weekly</changefreq></url>",
    ]
    for row in rows:
        chunks.append(f"<url><loc>{SITE_URL}/deal/{row['id']}</loc></url>")
    chunks.append("</urlset>")
    return Response("".join(chunks), media_type="application/xml")


@app.get("/api/deals/{deal_id}")
async def api_deal(deal_id: int):
    deal = await _get_deal(deal_id)
    if not deal:
        raise HTTPException(404, "deal not found")
    deal["posts"] = await _deal_posts(deal_id)
    deal["history"] = await _price_history(deal["product_key"])
    return deal


@app.get("/api/stats")
async def api_stats():
    return await _stats()


@app.get("/api/stream")
async def api_stream(request: Request):
    hub: EventHub = state["hub"]
    queue = hub.subscribe()

    async def generate():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False, default=str)
                yield f"data: {payload}\n\n"
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/collect")
async def api_collect(source: str | None = None):
    _require_collect()
    names = [source] if source else None
    summary = await _run_collect(names)
    return JSONResponse(summary)


@app.get("/api/debug/probe/{source}")
async def api_debug_probe(source: str):
    """Temporary HTML-structure probe; only when collect is enabled (Render)."""
    _require_collect()
    from app.sources.probe import probe_source

    return await probe_source(state["http"], source.lower())


@app.get("/api/debug/enrich/{deal_id}")
async def api_debug_enrich(deal_id: int, apply: int = 0):
    """Fetch community detail for a deal on the server and show parse result.

    Pass apply=1 to persist mall_url/thumbnail_url onto the deal/post.
    """
    _require_collect()
    import re

    from app.parse.links import extract_mall_url, is_mall_url
    from app.sources.detail import enrich_post

    posts = await _deal_posts(deal_id)
    if not posts:
        raise HTTPException(404, "deal posts not found")
    post = posts[0]
    source = post.get("source") or ""
    url = post.get("url") or ""
    detail = await enrich_post(state["http"], source, url)

    # Extra diagnostics: raw outbound http(s) candidates from the detail HTML.
    candidates: list[str] = []
    hrefs: list[str] = []
    encoding = "euc-kr" if "ppomppu.co.kr" in url else None
    try:
        fetched = await state["http"].get(url, encoding=encoding)
        html_text = fetched.text or ""
        for m in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", html_text, re.I):
            href = m.group(1).replace("&amp;", "&").strip()
            low = href.lower()
            if any(
                k in low
                for k in (
                    "gmarket",
                    "coupang",
                    "smartstore",
                    "11st",
                    "ssg",
                    "auction",
                    "ohou",
                    "link.php",
                    "out.php",
                    "goto",
                    "goodscode",
                    "url=",
                )
            ):
                hrefs.append(href[:300])
            if len(hrefs) >= 30:
                break
        for m in re.finditer(r"https?://[^\s<>\"']+", html_text):
            u = m.group(0).rstrip(").,;]'\"}")
            if any(k in u.lower() for k in ("gmarket", "coupang", "smartstore", "11st", "ssg", "auction", "ohou", "naver")):
                candidates.append(u)
            if len(candidates) >= 20:
                break
        # Product id crumbs even when URL is truncated in display text.
        codes = re.findall(r"goodscode[=:](\d{5,})", html_text, re.I)
    except Exception as exc:  # noqa: BLE001
        html_text = ""
        candidates = [f"fetch_error:{exc}"]
        hrefs = []
        codes = []

    applied = False
    if apply and (detail.mall_url or detail.thumbnail_url):
        db = _db()
        if detail.thumbnail_url:
            await db.execute(
                "UPDATE posts SET thumbnail_url=COALESCE(?, thumbnail_url) WHERE id=?",
                (detail.thumbnail_url, post["id"]),
            )
        await db.execute(
            """
            UPDATE deals
            SET mall_url=CASE WHEN ? IS NOT NULL THEN ? ELSE mall_url END,
                thumbnail_url=COALESCE(?, thumbnail_url)
            WHERE id=?
            """,
            (detail.mall_url, detail.mall_url, detail.thumbnail_url, deal_id),
        )
        await db.commit()
        applied = True
    return {
        "deal_id": deal_id,
        "source": source,
        "url": url,
        "list_title": post.get("title"),
        "enriched_title": detail.title,
        "mall_url": detail.mall_url,
        "thumbnail_url": detail.thumbnail_url,
        "applied": applied,
        "mall_candidates": candidates,
        "href_candidates": hrefs,
        "goodscodes": codes[:10] if html_text else [],
        "candidate_accepted": [u for u in candidates if is_mall_url(u)][:10],
        "extract_from_html": extract_mall_url(html_text[:80000]) if html_text else None,
        "outbound_resolve": await _debug_resolve_outbound(state["http"], url, hrefs),
    }


async def _debug_resolve_outbound(client, page_url: str, hrefs: list[str]) -> list[dict]:
    from urllib.parse import urljoin

    from app.parse.links import extract_mall_url, is_mall_url

    out: list[dict] = []
    for href in hrefs:
        if "link.php" not in href and "out.php" not in href:
            continue
        abs_url = urljoin(page_url, href)
        row = {"href": abs_url}
        try:
            result = await client.get(abs_url, timeout=20.0)
            row["final_url"] = result.url
            row["status"] = result.status
            row["is_mall"] = is_mall_url(result.url)
            row["nested_mall"] = extract_mall_url(result.text or "")
            row["body_head"] = (result.text or "")[:240]
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"
        out.append(row)
        if len(out) >= 3:
            break
    return out


async def _stats() -> dict:
    db = _db()
    cur = await db.execute("SELECT COUNT(*) AS c FROM posts")
    posts = (await cur.fetchone())["c"]
    cur = await db.execute("SELECT COUNT(*) AS c FROM deals")
    deals = (await cur.fetchone())["c"]
    cur = await db.execute(
        """
        SELECT COUNT(*) AS c FROM deals
        WHERE date(last_seen_at, '+9 hours')=date('now', '+9 hours')
          AND (grade LIKE '%핫딜%' OR grade LIKE '%특가%')
        """
    )
    today_hot = (await cur.fetchone())["c"]
    cur = await db.execute(
        """
        SELECT COUNT(*) AS c FROM deals
        WHERE date(last_seen_at, '+9 hours')=date('now', '+9 hours') AND grade LIKE '%초특가%'
        """
    )
    strong = (await cur.fetchone())["c"]
    last = await get_meta(db, "last_collect_at")
    summary_raw = await get_meta(db, "last_collect_summary")
    by_source_raw = await get_meta(db, "last_collect_by_source")
    last_collect = None
    by_source = None
    if summary_raw:
        try:
            last_collect = json.loads(summary_raw)
        except json.JSONDecodeError:
            last_collect = {"raw": summary_raw}
    if by_source_raw:
        try:
            by_source = json.loads(by_source_raw)
        except json.JSONDecodeError:
            by_source = {"raw": by_source_raw}
    return {
        "posts": posts,
        "deals": deals,
        "today_hot": today_hot,
        "strong": strong,
        "last_collect_at": last,
        "last_collect": last_collect,
        "collect_by_source": by_source,
    }


async def _list_deals(
    grade=None,
    seller=None,
    source=None,
    category=None,
    ids=None,
    limit=100,
    before_id=None,
) -> list[dict]:
    db = _db()
    sql = """
        SELECT d.*, GROUP_CONCAT(DISTINCT p.source) AS sources
        FROM deals d
        LEFT JOIN deal_posts dp ON dp.deal_id=d.id
        LEFT JOIN posts p ON p.id=dp.post_id
        WHERE 1=1
    """
    params: list = []
    if grade:
        sql += " AND d.grade LIKE ?"
        params.append(f"%{grade}%")
    if seller:
        sql += " AND d.seller = ?"
        params.append(seller)
    if source:
        sql += " AND p.source = ?"
        params.append(source)
    if category:
        sql += " AND d.category = ?"
        params.append(category)
    if ids:
        placeholders = ",".join("?" for _ in ids)
        sql += f" AND d.id IN ({placeholders})"
        params.extend(ids)
    if before_id:
        cur = await db.execute(
            "SELECT id, COALESCE(last_scored_at, last_seen_at) AS sort_at FROM deals WHERE id=?",
            (before_id,),
        )
        cursor = await cur.fetchone()
        if cursor:
            sql += (
                " AND (COALESCE(d.last_scored_at, d.last_seen_at) < ?"
                " OR (COALESCE(d.last_scored_at, d.last_seen_at) = ? AND d.id < ?))"
            )
            params.extend([cursor["sort_at"], cursor["sort_at"], cursor["id"]])
    sql += " GROUP BY d.id ORDER BY COALESCE(d.last_scored_at, d.last_seen_at) DESC, d.id DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(sql, params)
    return [dict(r) for r in await cur.fetchall()]


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
        if len(out) >= 80:
            break
    return out


def _fts_query(q: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", q)
    return " AND ".join(f'"{t}"' for t in tokens[:8] if t)


async def _search_deals(q: str, limit: int = 50) -> list[dict]:
    db = _db()
    fts = _fts_query(q)
    if fts:
        try:
            cur = await db.execute(
                """
                SELECT d.*, GROUP_CONCAT(DISTINCT p.source) AS sources
                FROM deals_fts f
                JOIN deals d ON d.id = f.rowid
                LEFT JOIN deal_posts dp ON dp.deal_id=d.id
                LEFT JOIN posts p ON p.id=dp.post_id
                WHERE f MATCH ?
                GROUP BY d.id
                ORDER BY rank
                LIMIT ?
                """,
                (fts, limit),
            )
            rows = [dict(r) for r in await cur.fetchall()]
            if rows:
                return rows
        except Exception:
            log.exception("fts search failed")
    like = f"%{q}%"
    cur = await db.execute(
        """
        SELECT d.*, GROUP_CONCAT(DISTINCT p.source) AS sources
        FROM deals d
        LEFT JOIN deal_posts dp ON dp.deal_id=d.id
        LEFT JOIN posts p ON p.id=dp.post_id
        WHERE d.product_name LIKE ? OR IFNULL(d.seller, '') LIKE ?
        GROUP BY d.id
        ORDER BY COALESCE(d.last_scored_at, d.last_seen_at) DESC, d.id DESC
        LIMIT ?
        """,
        (like, like, limit),
    )
    return [dict(r) for r in await cur.fetchall()]


def _deal_jsonld(deal: dict) -> dict:
    offer: dict = {
        "@type": "Offer",
        "url": f"{SITE_URL}/deal/{deal['id']}",
        "availability": "https://schema.org/InStock",
        "priceCurrency": "KRW",
    }
    if deal.get("price"):
        offer["price"] = str(deal["price"])
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": deal.get("product_name") or "핫딜",
        "url": f"{SITE_URL}/deal/{deal['id']}",
        "offers": offer,
    }
    if deal.get("seller"):
        data["brand"] = {"@type": "Brand", "name": deal["seller"]}
    if deal.get("thumbnail_url"):
        data["image"] = deal["thumbnail_url"]
    crumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "핫딜", "item": SITE_URL + "/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": deal.get("product_name") or "상세",
                "item": f"{SITE_URL}/deal/{deal['id']}",
            },
        ],
    }
    return {"@context": "https://schema.org", "@graph": [data, crumbs]}


async def _get_deal(deal_id: int) -> dict | None:
    cur = await _db().execute("SELECT * FROM deals WHERE id=?", (deal_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def _deal_posts(deal_id: int) -> list[dict]:
    cur = await _db().execute(
        """
        SELECT p.* FROM posts p
        JOIN deal_posts dp ON dp.post_id=p.id
        WHERE dp.deal_id=?
        ORDER BY COALESCE(p.posted_at, p.collected_at) DESC
        """,
        (deal_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def _price_history(product_key: str) -> list[dict]:
    cur = await _db().execute(
        """
        SELECT observed_at, price, seller, source
        FROM price_points
        WHERE product_key=?
        ORDER BY observed_at
        """,
        (product_key,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def _distinct(column: str) -> list[str]:
    cur = await _db().execute(
        f"SELECT DISTINCT {column} AS v FROM deals WHERE {column} IS NOT NULL AND {column}!='' ORDER BY v"
    )
    return [r["v"] for r in await cur.fetchall()]


async def _distinct_sources() -> list[str]:
    cur = await _db().execute("SELECT DISTINCT source AS v FROM posts ORDER BY v")
    return [r["v"] for r in await cur.fetchall()]
