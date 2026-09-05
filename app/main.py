from __future__ import annotations

import asyncio
import html
import json
import logging
import math
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.amazon_jp.pipeline import collect_amazon_jp
from app.amazon_jp.query import list_amazon_jp_deals
from app.config import (
    ADMIN_PASSWORD,
    AMAZON_JP_ENABLED,
    AMAZON_JP_INTERVAL_MINUTES,
    COLLECT_FAST_SECONDS,
    COLLECT_PROXY_SECONDS,
    COLLECT_SLOW_MINUTES,
    MALL_ENRICH_INTERVAL_SECONDS,
    ENABLE_COLLECT,
    FAMILY_SALE_INTERVAL_MINUTES,
    MVNO_ENABLED,
    MVNO_INTERVAL_MINUTES,
    PPOMPPU_INTERVAL_SECONDS,
    QUASARZONE_INTERVAL_MINUTES,
    PPOMPPU_PROXY_URL,
    SITE_URL,
    WATCHDOG_CHECK_SECONDS,
    WATCHDOG_ENABLED,
    WATCHDOG_STALE_MINUTES,
)
from app.db import connect, get_meta, upsert_family_sale, utcnow_iso
from app.engine import auth as user_auth
from app.engine import comments as deal_comments
from app.engine.alerts import add_sub, channels_ready, default_target, delete_sub, list_subs
from app.engine.category import CATEGORIES as DEAL_CATEGORIES
from app.engine.dedupe import collapse_duplicate_deals
from app.engine.ppomppu_enrich import enrich_missing_ppomppu_malls
from app.family.parse import parse_discount
from app.family.pipeline import collect_family_sales
from app.family.query import CATEGORIES, get_sale, list_sales, month_grid, parse_cats, parse_year_month
from app.events import EventHub
from app.http_client import PoliteClient
from app.pipeline import collect_and_process
from app.parse.mall import mall_key_from_url, mall_label_from_url
from app.parse.sanitize_html import is_thin_body_html
from app.parse.title import clean_deal_title
from app.sources.registry import (
    COLLECT_FAST_SOURCES,
    COLLECT_PROXY_SOURCES,
    COLLECT_QUASARZONE_SOURCES,
    COLLECT_SLOW_SOURCES,
    SOURCE_LABELS,
    get_sources,
)
from app.util.timeparse import format_clock, format_kst, format_relative

log = logging.getLogger("hotdeal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["kst"] = format_kst
TEMPLATES.env.filters["reltime"] = format_relative
TEMPLATES.env.filters["clock"] = format_clock
TEMPLATES.env.filters["mall_label"] = mall_label_from_url
TEMPLATES.env.filters["mall_key"] = mall_key_from_url
TEMPLATES.env.filters["clean_title"] = clean_deal_title
TEMPLATES.env.globals["site_url"] = SITE_URL
TEMPLATES.env.globals["amazon_jp_enabled"] = AMAZON_JP_ENABLED
TEMPLATES.env.globals["mvno_enabled"] = MVNO_ENABLED
# Cache-busting query param for /static/*.css|js. base.html actually reads
# `asset_v` (`{% set v = asset_v | default('', true) %}`) — the global must
# be named to match, or the template's local `v` always falls back to ''.
TEMPLATES.env.globals["asset_v"] = str(int(time.time()))
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
_orig_template_response = TEMPLATES.TemplateResponse


def _template_response(name, context, *args, **kwargs):
    ctx = dict(context)
    req = ctx.get("request")
    if req is not None:
        user = getattr(req.state, "user", None)
        ctx.setdefault("user", user)
        ctx.setdefault("is_admin", user_auth.is_admin_user(user))
        ctx.setdefault("oauth_ready", user_auth.providers_ready())
    return _orig_template_response(name, ctx, *args, **kwargs)


TEMPLATES.TemplateResponse = _template_response
STATIC_DIR = Path(__file__).parent / "static"
PAGE_SIZE = 40

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["db"] = await connect()
    state["http"] = PoliteClient()
    state["hub"] = EventHub()
    state["collect_lock"] = asyncio.Lock()
    state["ppomppu_enrich_lock"] = asyncio.Lock()
    state["last_collect_ts"] = time.monotonic()
    scheduler = None
    if ENABLE_COLLECT:
        scheduler = AsyncIOScheduler()
        if WATCHDOG_ENABLED:
            scheduler.add_job(
                _scheduled_watchdog,
                "interval",
                seconds=max(30, WATCHDOG_CHECK_SECONDS),
                id="watchdog",
                max_instances=1,
                coalesce=True,
                next_run_time=datetime.now() + timedelta(minutes=WATCHDOG_STALE_MINUTES),
            )
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
            _scheduled_collect_fast,
            "interval",
            seconds=COLLECT_FAST_SECONDS,
            id="collect_fast",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=25),
        )
        scheduler.add_job(
            _scheduled_collect_proxy,
            "interval",
            seconds=COLLECT_PROXY_SECONDS,
            id="collect_proxy",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=35),
        )
        scheduler.add_job(
            _scheduled_collect_quasarzone,
            "interval",
            minutes=max(1, QUASARZONE_INTERVAL_MINUTES),
            id="collect_quasarzone",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=45),
        )
        scheduler.add_job(
            _scheduled_collect_slow,
            "interval",
            minutes=COLLECT_SLOW_MINUTES,
            id="collect_slow",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=55),
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
        if AMAZON_JP_ENABLED:
            scheduler.add_job(
                _scheduled_amazon_jp,
                "interval",
                minutes=AMAZON_JP_INTERVAL_MINUTES,
                id="collect_amazon_jp",
                max_instances=1,
                coalesce=True,
                next_run_time=datetime.now() + timedelta(seconds=40),
            )
        if MVNO_ENABLED:
            scheduler.add_job(
                _scheduled_mvno,
                "interval",
                minutes=max(5, MVNO_INTERVAL_MINUTES),
                id="collect_mvno",
                max_instances=1,
                coalesce=True,
                next_run_time=datetime.now() + timedelta(seconds=60),
            )
        scheduler.add_job(
            _scheduled_ppomppu_mall_enrich,
            "interval",
            seconds=MALL_ENRICH_INTERVAL_SECONDS,
            id="enrich_ppomppu_malls",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=20),
        )
        log.info(
            "mall enrich worker enabled (proxy=%s)",
            "on" if PPOMPPU_PROXY_URL else "off",
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
        try:
            from app.sources import fm_browser

            await fm_browser.shutdown()
        except Exception:  # noqa: BLE001
            pass
        await state["db"].close()


app = FastAPI(title="자동 핫딜 탐지기", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def attach_user(request: Request, call_next):
    request.state.user = None
    if not request.url.path.startswith("/static") and state.get("db") is not None:
        try:
            request.state.user = await user_auth.user_from_request(request, state["db"])
        except Exception:
            log.exception("auth load failed")
    return await call_next(request)


async def _scheduled_watchdog() -> None:
    """Every collect tier updates state["last_collect_ts"] on success; the
    fastest tier runs every 30s, so if nothing has succeeded for several
    minutes the scheduler (or the event loop under it) is stuck even though
    HTTP may still be answering. Exit non-zero so the platform's restart
    policy — which a plain hang never triggers on its own — takes over."""
    last = state.get("last_collect_ts")
    if last is None:
        return
    stale_for = time.monotonic() - last
    limit = WATCHDOG_STALE_MINUTES * 60
    if stale_for > limit:
        log.critical(
            "watchdog: no collect tick in %.0fs (limit %ds) — exiting for restart",
            stale_for,
            limit,
        )
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:  # noqa: BLE001
                pass
        os._exit(1)


async def _scheduled_collect() -> None:
    await _run_collect(["ppomppu"])


async def _scheduled_collect_fast() -> None:
    await _run_collect(COLLECT_FAST_SOURCES)


async def _scheduled_collect_proxy() -> None:
    await _run_collect(COLLECT_PROXY_SOURCES)


async def _scheduled_collect_quasarzone() -> None:
    await _run_collect(COLLECT_QUASARZONE_SOURCES)


async def _scheduled_collect_slow() -> None:
    await _run_collect(COLLECT_SLOW_SOURCES)


async def _scheduled_family() -> None:
    async with state["collect_lock"]:
        try:
            await collect_family_sales(state["db"], state["http"])
        except Exception:
            log.exception("family collect failed")


async def _scheduled_amazon_jp() -> None:
    async with state["collect_lock"]:
        try:
            await collect_amazon_jp(state["db"], state["http"])
        except Exception:
            log.exception("amazon jp collect failed")


async def _scheduled_mvno() -> None:
    from app.mvno.pipeline import collect_mvno_plans

    async with state["collect_lock"]:
        try:
            await collect_mvno_plans(state["db"], state["http"])
        except Exception:
            log.exception("mvno collect failed")


async def _scheduled_ppomppu_mall_enrich() -> None:
    await _run_mall_enrich()


async def _kick_mall_enrich(deal_ids: list[int]) -> None:
    if not deal_ids:
        return
    lock = state.get("ppomppu_enrich_lock")
    # Don't queue behind a long enrich tick; the 30s scheduler will catch up.
    if lock is None or lock.locked():
        return
    try:
        await _run_mall_enrich(deal_ids=deal_ids, limit=max(6, len(deal_ids)))
    except Exception:
        log.exception("immediate mall enrich failed")


async def _run_mall_enrich(
    *, deal_ids: list[int] | None = None, limit: int | None = None
) -> dict:
    lock = state.get("ppomppu_enrich_lock")
    if lock is None:
        return {}
    async with lock:
        conn = await connect()
        try:
            out = await enrich_missing_ppomppu_malls(
                conn, state["http"], deal_ids=deal_ids, limit=limit
            )
        except Exception:
            log.exception("ppomppu mall enrich failed")
            return {}
        finally:
            await conn.close()
        cards = []
        for raw in out.get("cards") or []:
            try:
                card = _clean_deal(dict(raw))
            except Exception:
                card = dict(raw)
            card["list_ready"] = True
            cards.append(card)
        out["cards"] = cards
        if cards:
            try:
                stats = await _stats()
            except Exception:
                stats = None
            state["hub"].publish(
                {
                    "type": "tick",
                    "stats": stats,
                    "sources": {},
                    "new_posts": 0,
                    "items": cards,
                }
            )
        return out


async def _run_collect(names: list[str] | None) -> dict:
    # Own SQLite connection so fast/proxy/slow ticks can overlap under WAL
    # without sharing state["db"] with request handlers.
    from app.pipeline import fetch_deal_card

    conn = await connect()
    try:
        try:
            summary = await collect_and_process(conn, get_sources(names), state["http"])
        except Exception:
            log.exception("scheduled collect failed")
            return {"errors": ["collect failed"], "new_deals": [], "sources": {}}
        state["last_collect_ts"] = time.monotonic()

        new_deals = summary.get("new_deals") or []
        missing = [
            int(d["id"])
            for d in new_deals
            if d.get("id") and not (d.get("mall_url") or "").strip()
        ]
        # Fill shop links before the live list updates, so cards and 구매하기
        # appear together instead of a delayed buy button.
        if missing:
            lock = state.get("ppomppu_enrich_lock")
            if lock is not None:
                async with lock:
                    try:
                        await enrich_missing_ppomppu_malls(
                            conn,
                            state["http"],
                            deal_ids=missing,
                            limit=len(missing),
                        )
                    except Exception:
                        log.exception("pre-publish mall enrich failed")

        ready: list[dict] = []
        for d in new_deals:
            did = d.get("id")
            if not did:
                continue
            try:
                card = await fetch_deal_card(conn, int(did))
            except Exception:
                card = None
            item = _clean_deal(dict(card)) if card else dict(d)
            item["list_ready"] = True
            ready.append(item)
        summary["new_deals"] = ready

        stats = await _stats()
        state["hub"].publish(
            {
                "type": "tick",
                "stats": stats,
                "sources": summary.get("sources") or {},
                "new_posts": summary.get("new_posts") or 0,
                "items": ready,
            }
        )
        return summary
    finally:
        await conn.close()


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
    try:
        deals = await _list_deals(
            grade=grade, seller=seller, source=None, category=category or None, limit=PAGE_SIZE
        )
    except Exception:
        log.exception("index list failed")
        deals = []
    try:
        sellers = await _distinct("seller")
        sources = await _distinct_sources()
        category_counts, deals_total = await _category_counts()
    except Exception:
        log.exception("index filters failed")
        sellers, sources = [], []
        category_counts, deals_total = {}, 0
    ordered_sources = [s.name for s in get_sources() if s.name in set(sources)]
    for name in sources:
        if name not in ordered_sources:
            ordered_sources.append(name)
    ctx = {
        "request": request,
        "stats": stats,
        "deals": deals,
        "grade": grade or "",
        "seller": seller or "",
        "source": source or "",
        "category": category,
        "categories": DEAL_CATEGORIES,
        "category_counts": category_counts,
        "deals_total": deals_total,
        "sellers": sellers,
        "sources": ordered_sources,
        "source_labels": SOURCE_LABELS,
        "page_size": PAGE_SIZE,
        "has_more": len(deals) >= PAGE_SIZE,
        "nav": "hotdeal",
    }
    try:
        return TEMPLATES.TemplateResponse("index.html", ctx)
    except Exception:
        log.exception("index template failed")
        items = []
        for d in deals:
            name = html.escape(str(d.get("product_name") or "(제목 없음)"))
            items.append(f"<li>{name}</li>")
        nav_links = (
            "<a href='/amazon-jp'>일마존</a> · <a href='/family'>패밀리세일</a>"
            if AMAZON_JP_ENABLED
            else "<a href='/family'>패밀리세일</a>"
        )
        return HTMLResponse(
            "<!doctype html><html lang='ko'><meta charset='utf-8'><title>핫딜모음</title>"
            f"<body><p>{nav_links}</p><h1>핫딜</h1><ul>"
            + "".join(items)
            + "</ul></body></html>"
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
            "nav": "admin",
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
                "nav": "admin",
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
    user = getattr(request.state, "user", None)
    user_keywords = await user_auth.list_keywords(_db(), user["id"]) if user else []
    return TEMPLATES.TemplateResponse(
        "alerts.html",
        {
            "request": request,
            "nav": "alerts",
            "authed": _is_admin(request),
            "subs": [_public_sub(s) for s in subs],
            "ready": channels_ready(),
            "user_keywords": user_keywords,
            "error": request.query_params.get("error"),
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
    keyword_id: int | None = Form(None),
):
    user = getattr(request.state, "user", None)
    if action == "user_notify" and user:
        try:
            await user_auth.set_notify(_db(), user["id"], channel or "", target or "")
            user = await user_auth.get_user(_db(), user["id"])
            await user_auth.sync_user_alert_subs(_db(), user or {})
            await _db().commit()
        except Exception:
            log.exception("user notify failed")
            return RedirectResponse("/alerts?error=notify", status_code=303)
    if action == "user_keyword" and user:
        try:
            await user_auth.add_keyword(_db(), user["id"], keyword or "", min_grade or "핫딜")
            user = await user_auth.get_user(_db(), user["id"])
            await user_auth.sync_user_alert_subs(_db(), user or {})
            await _db().commit()
        except Exception:
            log.exception("user keyword failed")
            return RedirectResponse("/alerts?error=keyword", status_code=303)
        return RedirectResponse("/alerts", status_code=303)
    if action == "user_keyword_delete" and user and keyword_id:
        await user_auth.delete_keyword(_db(), user["id"], keyword_id)
        user = await user_auth.get_user(_db(), user["id"])
        await user_auth.sync_user_alert_subs(_db(), user or {})
        await _db().commit()
        return RedirectResponse("/alerts", status_code=303)
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


def _require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user_auth.is_admin_user(user):
        raise HTTPException(403, "admin only")
    return user


@app.get("/amazon-jp", response_class=HTMLResponse)
async def amazon_jp_index(request: Request):
    if not AMAZON_JP_ENABLED:
        raise HTTPException(404, "일마존 메뉴가 비활성화되어 있습니다")
    deals = await list_amazon_jp_deals(_db())
    last = await get_meta(_db(), "last_amazon_jp_collect_at")
    return TEMPLATES.TemplateResponse(
        "amazon_jp.html",
        {
            "request": request,
            "nav": "amazon_jp",
            "deals": deals,
            "last": last,
        },
    )


@app.get("/mvno", response_class=HTMLResponse)
async def mvno_index(request: Request, sort: str = "fee", mno: str | None = None):
    if not MVNO_ENABLED:
        raise HTTPException(404, "알뜰요금제 메뉴가 비활성화되어 있습니다")
    from app.mvno.query import list_event_plans, mno_options

    db = _db()
    plans = await list_event_plans(db, sort=sort, mno=mno or None)
    last = await get_meta(db, "last_mvno_collect_at")
    return TEMPLATES.TemplateResponse(
        "mvno.html",
        {
            "request": request,
            "nav": "mvno",
            "plans": plans,
            "mnos": await mno_options(db),
            "sort": sort,
            "mno": mno or "",
            "last": last,
        },
    )


@app.post("/api/mvno/collect")
async def api_mvno_collect():
    if not MVNO_ENABLED:
        raise HTTPException(404, "알뜰요금제 메뉴가 비활성화되어 있습니다")
    _require_collect()
    from app.mvno.pipeline import collect_mvno_plans

    async with state["collect_lock"]:
        summary = await collect_mvno_plans(state["db"], state["http"])
    return JSONResponse(summary)


@app.post("/api/family/collect")
async def api_family_collect():
    _require_collect()
    async with state["collect_lock"]:
        summary = await collect_family_sales(state["db"], state["http"])
    return JSONResponse(summary)


@app.post("/api/amazon-jp/collect")
async def api_amazon_jp_collect():
    if not AMAZON_JP_ENABLED:
        raise HTTPException(404, "일마존 메뉴가 비활성화되어 있습니다")
    _require_collect()
    async with state["collect_lock"]:
        summary = await collect_amazon_jp(state["db"], state["http"])
    return JSONResponse(summary)


def _admin_token() -> str:
    return sha256(f"family-admin:{ADMIN_PASSWORD}".encode()).hexdigest()


def _is_admin(request: Request) -> bool:
    return bool(ADMIN_PASSWORD) and request.cookies.get("family_admin") == _admin_token()


def _require_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "login required")
    return user


def _login_redirect(user_id: int, dest: str = "/") -> RedirectResponse:
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(
        user_auth.SESSION_COOKIE,
        user_auth.sign_user_id(user_id),
        httponly=True,
        samesite="lax",
        secure=user_auth.cookie_secure(),
        max_age=user_auth.SESSION_MAX_AGE,
        path="/",
    )
    resp.delete_cookie(user_auth.OAUTH_COOKIE, path="/")
    return resp


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    if getattr(request.state, "user", None):
        return RedirectResponse("/", status_code=303)
    messages = {
        "provider": "이 로그인 방법은 아직 설정되지 않았습니다.",
        "oauth": "로그인에 실패했습니다. 잠시 후 다시 시도하세요.",
        "state": "로그인 요청이 만료되었습니다. 다시 눌러 주세요.",
        "denied": "로그인이 취소되었습니다.",
        "credentials": "아이디 또는 비밀번호가 올바르지 않습니다.",
    }
    return TEMPLATES.TemplateResponse(
        "login.html",
        {"request": request, "nav": "hotdeal", "error": messages.get(error or "", "")},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
):
    if getattr(request.state, "user", None):
        return RedirectResponse("/", status_code=303)
    user = await user_auth.authenticate_local(_db(), username, password)
    if not user:
        return RedirectResponse("/login?error=credentials", status_code=303)
    dest = "/" if user_auth.is_admin_user(user) else "/alerts"
    return _login_redirect(int(user["id"]), dest)


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(user_auth.SESSION_COOKIE, path="/")
    return resp


@app.get("/auth/{provider}")
async def auth_start(provider: str):
    if provider not in user_auth.PROVIDERS or not user_auth.providers_ready().get(provider):
        return RedirectResponse("/login?error=provider", status_code=303)
    cookie, nonce = user_auth.new_oauth_state(provider)
    resp = RedirectResponse(user_auth.authorize_url(provider, nonce), status_code=302)
    resp.set_cookie(
        user_auth.OAUTH_COOKIE,
        cookie,
        httponly=True,
        samesite="lax",
        secure=user_auth.cookie_secure(),
        max_age=600,
        path="/",
    )
    return resp


@app.get("/auth/{provider}/callback")
async def auth_callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return RedirectResponse("/login?error=denied", status_code=303)
    if provider not in user_auth.PROVIDERS or not code:
        return RedirectResponse("/login?error=oauth", status_code=303)
    if not user_auth.oauth_cookie_ok(request.cookies.get(user_auth.OAUTH_COOKIE), provider, state):
        return RedirectResponse("/login?error=state", status_code=303)
    try:
        profile = await user_auth.exchange_code(provider, code)
        user = await user_auth.upsert_oauth_user(_db(), provider=provider, profile=profile)
    except Exception:
        log.exception("oauth callback failed provider=%s", provider)
        return RedirectResponse("/login?error=oauth", status_code=303)
    return _login_redirect(int(user["id"]), "/alerts")


class BookmarkIn(BaseModel):
    ids: list[int] = Field(default_factory=list)


class CommentIn(BaseModel):
    nickname: str = ""
    pin: str = ""
    body: str = ""
    parent_id: int | None = None


class CommentDeleteIn(BaseModel):
    pin: str = ""


class ReactionIn(BaseModel):
    kind: str = ""


class ReportIn(BaseModel):
    reason: str = ""
    detail: str = ""


CLIENT_COOKIE = "hd_cid"
CLIENT_COOKIE_AGE = 60 * 60 * 24 * 365


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "")


def _client_key(request: Request) -> str:
    existing = (request.cookies.get(CLIENT_COOKIE) or "").strip()
    if existing and len(existing) >= 8:
        return existing
    return secrets.token_urlsafe(16)


def _set_client_cookie(resp, key: str) -> None:
    resp.set_cookie(
        CLIENT_COOKIE,
        key,
        max_age=CLIENT_COOKIE_AGE,
        httponly=False,
        samesite="lax",
        secure=user_auth.cookie_secure(),
        path="/",
    )


@app.get("/api/me")
async def api_me(request: Request):
    return {"user": user_auth.public_user(getattr(request.state, "user", None))}


@app.get("/api/me/bookmarks")
async def api_me_bookmarks(request: Request):
    user = _require_user(request)
    ids = await user_auth.list_bookmark_ids(_db(), user["id"])
    return {"ids": ids}


@app.put("/api/me/bookmarks")
async def api_me_bookmarks_put(request: Request, payload: BookmarkIn):
    user = _require_user(request)
    ids = await user_auth.replace_bookmarks(_db(), user["id"], payload.ids)
    return {"ids": ids}


@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def deal_detail(request: Request, deal_id: int):
    deal = await _get_deal(deal_id)
    if not deal:
        raise HTTPException(404, "deal not found")
    posts = await _deal_posts(deal_id)
    body_html, body_source = _pick_body_html(posts)
    deal["body_html"] = body_html
    deal["body_source"] = body_source
    if ENABLE_COLLECT and (
        not (deal.get("mall_url") or "").strip()
        or not body_html
        or is_thin_body_html(body_html)
    ):
        asyncio.create_task(_kick_mall_enrich([deal_id]))
    history = await _price_history(deal["product_key"])
    similar = await _similar_deals(deal)
    key = _client_key(request)
    comments = [
        deal_comments.public_comment(
            row,
            mine=row.get("client_key") == key,
            admin=user_auth.is_admin_user(getattr(request.state, "user", None)),
        )
        for row in await deal_comments.list_comments(_db(), deal_id)
    ]
    reactions = await deal_comments.reaction_snapshot(_db(), deal_id, key)
    counts = await deal_comments.comment_counts(_db(), [deal_id])
    deal["user_comments"] = counts.get(deal_id, 0)
    resp = TEMPLATES.TemplateResponse(
        "deal.html",
        {
            "request": request,
            "nav": "hotdeal",
            "deal": deal,
            "posts": posts,
            "history": history,
            "similar": similar,
            "comments": comments,
            "reactions": reactions,
            "comment_count": deal["user_comments"],
            "source_labels": SOURCE_LABELS,
            "jsonld": _deal_jsonld(deal),
        },
    )
    _set_client_cookie(resp, key)
    return resp


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
    try:
        items = await _list_deals(
            grade=grade,
            seller=seller,
            source=source,
            category=category,
            ids=id_list,
            limit=limit,
            before_id=None if id_list else before_id,
        )
        return Response(
            json.dumps(items, ensure_ascii=False, default=str, allow_nan=False),
            media_type="application/json",
        )
    except Exception as exc:
        log.exception("api deals failed")
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = ""):
    q = (q or "").strip()
    deals = await _search_deals(q, limit=50) if q else []
    return TEMPLATES.TemplateResponse(
        "search.html",
        {
            "request": request,
            "nav": "search",
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
        "Disallow: /login\n"
        "Disallow: /auth/\n"
        "Disallow: /admin/\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@app.get("/sitemap.xml")
async def sitemap():
    cur = await _db().execute(
        "SELECT id FROM deals ORDER BY last_seen_at DESC, id DESC LIMIT 400"
    )
    rows = await cur.fetchall()
    chunks = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"<url><loc>{SITE_URL}/</loc><changefreq>hourly</changefreq></url>",
        f"<url><loc>{SITE_URL}/family</loc><changefreq>daily</changefreq></url>",
        f"<url><loc>{SITE_URL}/search</loc><changefreq>weekly</changefreq></url>",
    ]
    if AMAZON_JP_ENABLED:
        chunks.insert(
            4,
            f"<url><loc>{SITE_URL}/amazon-jp</loc><changefreq>hourly</changefreq></url>",
        )
    for row in rows:
        chunks.append(f"<url><loc>{SITE_URL}/deal/{row['id']}</loc></url>")
    chunks.append("</urlset>")
    return Response("".join(chunks), media_type="application/xml")


@app.get("/api/deals/{deal_id}")
async def api_deal(deal_id: int):
    try:
        deal = await _get_deal(deal_id)
        if not deal:
            raise HTTPException(404, "deal not found")
        posts = await _deal_posts(deal_id)
        body_html, body_source = _pick_body_html(posts)
        deal["body_html"] = body_html
        deal["body_source"] = body_source
        deal["posts"] = [
            {k: _json_safe(v) for k, v in row.items() if k != "raw_json"}
            for row in posts
        ]
        deal["history"] = [
            {k: _json_safe(v) for k, v in row.items()}
            for row in await _price_history(deal["product_key"])
        ]
        deal["similar"] = await _similar_deals(deal)
        counts = await deal_comments.comment_counts(_db(), [deal_id])
        deal["user_comments"] = counts.get(deal_id, 0)
        deal["comment_count"] = deal["user_comments"]
    except HTTPException:
        raise
    except Exception:
        log.exception("api deal failed id=%s", deal_id)
        raise HTTPException(503, "deal temporarily unavailable")
    if ENABLE_COLLECT and (
        not (deal.get("mall_url") or "").strip()
        or not deal.get("body_html")
        or is_thin_body_html(deal.get("body_html"))
    ):
        asyncio.create_task(_kick_mall_enrich([deal_id]))
    return JSONResponse(deal)


@app.get("/api/deals/{deal_id}/market")
async def api_deal_market(deal_id: int, refresh: int = 0):
    """커뮤니티 price_points 기반 판매처별 최저가 비교 (네이버 API 미사용)."""
    deal = await _get_deal(deal_id)
    if not deal:
        raise HTTPException(404, "deal not found")
    return await _community_market_compare(
        product_key=deal.get("product_key") or "",
        deal_price=deal.get("price"),
        deal_seller=deal.get("seller"),
        deal_url=deal.get("mall_url") or deal.get("deal_url"),
    )


@app.get("/api/deals/{deal_id}/comments")
async def api_deal_comments(request: Request, deal_id: int, after: int = 0):
    if not await _get_deal(deal_id):
        raise HTTPException(404, "deal not found")
    key = _client_key(request)
    admin = user_auth.is_admin_user(getattr(request.state, "user", None))
    rows = await deal_comments.list_comments(_db(), deal_id, after_id=after)
    items = [
        deal_comments.public_comment(row, mine=row.get("client_key") == key, admin=admin)
        for row in rows
    ]
    counts = await deal_comments.comment_counts(_db(), [deal_id])
    reactions = await deal_comments.reaction_snapshot(_db(), deal_id, key)
    resp = JSONResponse(
        {
            "items": items,
            "count": counts.get(deal_id, 0),
            "me": key,
            "is_admin": admin,
            "reactions": reactions,
        }
    )
    _set_client_cookie(resp, key)
    return resp


@app.post("/api/deals/{deal_id}/comments")
async def api_deal_comments_post(request: Request, deal_id: int, payload: CommentIn):
    if not await _get_deal(deal_id):
        raise HTTPException(404, "deal not found")
    key = _client_key(request)
    try:
        item = await deal_comments.add_comment(
            _db(),
            deal_id=deal_id,
            nickname=payload.nickname,
            pin=payload.pin,
            body=payload.body,
            parent_id=payload.parent_id,
            client_key=key,
            user=getattr(request.state, "user", None),
            ip=_client_ip(request),
        )
    except deal_comments.CommentError as exc:
        raise HTTPException(400, str(exc)) from exc
    resp = JSONResponse(item)
    _set_client_cookie(resp, key)
    return resp


@app.delete("/api/comments/{comment_id}")
async def api_comment_delete(request: Request, comment_id: int, payload: CommentDeleteIn):
    key = _client_key(request)
    try:
        await deal_comments.delete_comment(
            _db(),
            comment_id,
            pin=payload.pin,
            client_key=key,
            is_admin=user_auth.is_admin_user(getattr(request.state, "user", None)),
        )
    except deal_comments.CommentError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.post("/api/deals/{deal_id}/reactions")
async def api_deal_reactions(request: Request, deal_id: int, payload: ReactionIn):
    if not await _get_deal(deal_id):
        raise HTTPException(404, "deal not found")
    key = _client_key(request)
    try:
        snap = await deal_comments.toggle_reaction(
            _db(), deal_id=deal_id, client_key=key, kind=payload.kind
        )
    except deal_comments.CommentError as exc:
        raise HTTPException(400, str(exc)) from exc
    resp = JSONResponse(snap)
    _set_client_cookie(resp, key)
    return resp


@app.post("/api/deals/{deal_id}/report")
async def api_deal_report(request: Request, deal_id: int, payload: ReportIn):
    if not await _get_deal(deal_id):
        raise HTTPException(404, "deal not found")
    key = _client_key(request)
    try:
        await deal_comments.add_report(
            _db(),
            deal_id=deal_id,
            reason=payload.reason,
            detail=payload.detail,
            client_key=key,
        )
    except deal_comments.CommentError as exc:
        raise HTTPException(400, str(exc)) from exc
    resp = JSONResponse({"ok": True})
    _set_client_cookie(resp, key)
    return resp


@app.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports(request: Request):
    _require_admin(request)
    rows = await deal_comments.list_reports(_db())
    return TEMPLATES.TemplateResponse(
        "admin_reports.html",
        {"request": request, "nav": "admin", "reports": rows},
    )


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
async def api_collect(request: Request, source: str | None = None):
    _require_collect()
    _require_admin(request)
    names = [source] if source else None
    summary = await _run_collect(names)
    return JSONResponse(summary)


@app.post("/api/ppomppu/enrich-malls")
async def api_ppomppu_enrich_malls(request: Request, limit: int = 12):
    """Manually run buy-link enrich for deals missing mall_url."""
    _require_collect()
    _require_admin(request)
    lock = state.get("ppomppu_enrich_lock")
    if lock is None:
        raise HTTPException(503, "enrich lock unavailable")
    safe = {k: v for k, v in (out or {}).items() if k != "cards"}
    return JSONResponse(safe)


@app.get("/api/debug/feed")
async def api_debug_feed(limit: int = 40):
    try:
        rows = await _list_deals(limit=limit)
        sample = rows[0] if rows else {}
        dumped = json.dumps(rows[:3], ensure_ascii=False, default=str, allow_nan=False)
        return {
            "ok": True,
            "n": len(rows),
            "keys": sorted(sample.keys()),
            "ids": [r.get("id") for r in rows[:10]],
            "dump_len": len(dumped),
        }
    except Exception as exc:
        log.exception("debug feed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


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
    if apply and (detail.mall_url or detail.thumbnail_url or detail.body_html):
        db = _db()
        if detail.thumbnail_url:
            await db.execute(
                "UPDATE posts SET thumbnail_url=COALESCE(?, thumbnail_url) WHERE id=?",
                (detail.thumbnail_url, post["id"]),
            )
        if detail.body_html:
            await db.execute(
                "UPDATE posts SET body_html=? WHERE id=?",
                (detail.body_html, post["id"]),
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
        "body_html_len": len(detail.body_html or ""),
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
    pp_enrich_raw = await get_meta(db, "last_ppomppu_mall_enrich")
    last_collect = None
    by_source = None
    pp_enrich = None
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
    if pp_enrich_raw:
        try:
            pp_enrich = json.loads(pp_enrich_raw)
        except json.JSONDecodeError:
            pp_enrich = {"raw": pp_enrich_raw}
    return {
        "posts": posts,
        "deals": deals,
        "today_hot": today_hot,
        "strong": strong,
        "last_collect_at": last,
        "last_collect": last_collect,
        "collect_by_source": by_source,
        "ppomppu_proxy_configured": bool(PPOMPPU_PROXY_URL),
        "last_ppomppu_mall_enrich": pp_enrich,
        "last_amazon_jp_collect_at": await get_meta(db, "last_amazon_jp_collect_at"),
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
    sql = "SELECT * FROM deals WHERE 1=1"
    params: list = []
    if grade:
        sql += " AND grade LIKE ?"
        params.append(f"%{grade}%")
    if seller:
        sql += " AND seller = ?"
        params.append(seller)
    if category:
        sql += " AND category = ?"
        params.append(category)
    if source:
        sql += (
            " AND id IN (SELECT dp.deal_id FROM deal_posts dp"
            " JOIN posts p ON p.id=dp.post_id WHERE p.source=?)"
        )
        params.append(source)
    if ids:
        placeholders = ",".join("?" for _ in ids)
        sql += f" AND id IN ({placeholders})"
        params.extend(ids)
    else:
        # Hide brand-new cards until a shop link is ready (or a short grace
        # window passes for the rare post with no mall link).
        sql += (
            " AND ("
            " (mall_url IS NOT NULL AND TRIM(mall_url) != '')"
            " OR first_seen_at <= datetime('now', '-3 minutes')"
            " )"
        )
    if before_id:
        cur = await db.execute("SELECT id, last_seen_at FROM deals WHERE id=?", (before_id,))
        cursor = await cur.fetchone()
        if cursor:
            sql += " AND (last_seen_at < ? OR (last_seen_at = ? AND id < ?))"
            params.extend([cursor["last_seen_at"], cursor["last_seen_at"], cursor["id"]])
    sql += " ORDER BY last_seen_at DESC, id DESC LIMIT ?"
    params.append(limit)
    id_sql = "SELECT id FROM deals" + sql[len("SELECT * FROM deals") :]
    cur = await db.execute(id_sql, params)
    deal_ids = [int(r["id"]) for r in await cur.fetchall()]
    deals: list[dict] = []
    for deal_id in deal_ids:
        try:
            row_cur = await db.execute("SELECT * FROM deals WHERE id=?", (deal_id,))
            row = await row_cur.fetchone()
            if row:
                deals.append(_clean_deal(dict(row)))
        except Exception:
            log.exception("skip deal %s", deal_id)
    try:
        deals = await _attach_sources(db, deals)
    except Exception:
        log.exception("attach sources failed")
        for deal in deals:
            deal.setdefault("sources", "")
    return collapse_duplicate_deals(deals)


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").replace("\x00", "")
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, memoryview):
        return _json_safe(value.tobytes())
    return str(value)


def _as_int(value) -> int | None:
    value = _json_safe(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d-]", "", value)
        if digits in ("", "-"):
            return None
        try:
            return int(digits)
        except ValueError:
            return None
    return None


def _as_float(value) -> float | None:
    value = _json_safe(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").strip())
        except ValueError:
            return None
    return None


def _clean_deal(deal: dict) -> dict:
    out = {key: _json_safe(value) for key, value in deal.items()}
    out["price"] = _as_int(out.get("price"))
    out["baseline_price"] = _as_int(out.get("baseline_price"))
    out["unit_price"] = _as_int(out.get("unit_price"))
    out["comments"] = _as_int(out.get("comments")) or 0
    out["user_comments"] = _as_int(out.get("user_comments")) or 0
    out["discount_rate"] = _as_float(out.get("discount_rate"))
    if out.get("grade") is not None:
        out["grade"] = str(out["grade"])
    if out.get("product_name") is not None:
        out["product_name"] = str(out["product_name"])
    if out.get("seller") is not None:
        out["seller"] = str(out["seller"])
    if out.get("sources") is not None:
        out["sources"] = str(out["sources"])
    for ts_key in ("last_seen_at", "first_seen_at", "last_scored_at", "created_at", "updated_at"):
        if out.get(ts_key) is not None:
            out[ts_key] = str(out[ts_key])
    return out


async def _attach_sources(db, deals: list[dict]) -> list[dict]:
    if not deals:
        return deals
    ids = [d["id"] for d in deals]
    placeholders = ",".join("?" for _ in ids)
    cur = await db.execute(
        f"""
        SELECT dp.deal_id, p.source, IFNULL(p.comments, 0) AS comments
        FROM deal_posts dp
        JOIN posts p ON p.id=dp.post_id
        WHERE dp.deal_id IN ({placeholders})
        ORDER BY p.collected_at ASC, p.id ASC
        """,
        ids,
    )
    buckets: dict[int, list[str]] = {}
    comments: dict[int, int] = {}
    for row in await cur.fetchall():
        deal_id = row["deal_id"]
        src = row["source"]
        if src:
            bucket = buckets.setdefault(deal_id, [])
            if src not in bucket:
                bucket.append(src)  # ordered oldest-collected first
        try:
            c = int(row["comments"] or 0)
        except (TypeError, ValueError):
            c = 0
        if c > comments.get(deal_id, 0):
            comments[deal_id] = c
    user_counts = await deal_comments.comment_counts(db, ids)
    for deal in deals:
        bucket = buckets.get(deal["id"], [])
        deal["sources"] = ",".join(bucket)
        # List cards show only the source that first picked the deal up; the
        # detail page still shows every source via `sources`.
        deal["first_source"] = bucket[0] if bucket else ""
        deal["comments"] = comments.get(deal["id"], 0)
        deal["user_comments"] = user_counts.get(deal["id"], 0)
    return deals


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
                SELECT d.*, GROUP_CONCAT(DISTINCT p.source) AS sources,
                       MAX(IFNULL(p.comments, 0)) AS comments
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
            rows = [_clean_deal(dict(r)) for r in await cur.fetchall()]
            if rows:
                return await _attach_user_comments(rows)
        except Exception:
            log.exception("fts search failed")
    like = f"%{q}%"
    cur = await db.execute(
        """
        SELECT d.*, GROUP_CONCAT(DISTINCT p.source) AS sources,
               MAX(IFNULL(p.comments, 0)) AS comments
        FROM deals d
        LEFT JOIN deal_posts dp ON dp.deal_id=d.id
        LEFT JOIN posts p ON p.id=dp.post_id
        WHERE d.product_name LIKE ? OR IFNULL(d.seller, '') LIKE ?
        GROUP BY d.id
        ORDER BY d.last_seen_at DESC, d.id DESC
        LIMIT ?
        """,
        (like, like, limit),
    )
    return await _attach_user_comments([_clean_deal(dict(r)) for r in await cur.fetchall()])


async def _attach_user_comments(deals: list[dict]) -> list[dict]:
    if not deals:
        return deals
    counts = await deal_comments.comment_counts(_db(), [d["id"] for d in deals])
    for deal in deals:
        deal["user_comments"] = counts.get(deal["id"], 0)
    return deals


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
    if not row:
        return None
    deal = _clean_deal(dict(row))
    try:
        await _attach_sources(_db(), [deal])
    except Exception:
        deal.setdefault("sources", "")
        deal.setdefault("comments", 0)
        deal.setdefault("user_comments", 0)
    return deal


async def _similar_deals(deal: dict, limit: int = 6) -> list[dict]:
    category = (deal.get("category") or "").strip()
    if not category:
        return []
    cur = await _db().execute(
        """
        SELECT * FROM deals
        WHERE category=? AND id!=? AND IFNULL(status,'') != 'expired'
        ORDER BY IFNULL(score, 0) DESC, last_seen_at DESC, id DESC
        LIMIT ?
        """,
        (category, deal["id"], limit),
    )
    rows = [_clean_deal(dict(r)) for r in await cur.fetchall()]
    try:
        return await _attach_sources(_db(), rows)
    except Exception:
        return rows


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


def _pick_body_html(posts: list[dict]) -> tuple[str | None, str | None]:
    """Prefer the richest sanitized community body among linked posts."""
    from app.parse.sanitize_html import is_thin_body_html, strip_board_chrome

    best_html: str | None = None
    best_source: str | None = None
    best_key = (-1, -1)  # (not_thin, length)
    for row in posts or []:
        html = (strip_board_chrome(row.get("body_html")) or "").strip()
        if not html:
            continue
        key = (0 if is_thin_body_html(html) else 1, len(html))
        if key > best_key:
            best_html = html
            best_source = (row.get("source") or "").strip() or None
            best_key = key
    return best_html, best_source


async def _price_history(product_key: str) -> list[dict]:
    """딜 게시 가격 이력. 네이버 시드 행은 제외하고 커뮤니티 관측만 반환."""
    cur = await _db().execute(
        """
        SELECT observed_at, price, seller, source
        FROM price_points
        WHERE product_key=?
          AND IFNULL(source, '') != 'naver'
        ORDER BY observed_at
        """,
        (product_key,),
    )
    return [dict(r) for r in await cur.fetchall()]


def _norm_mall(name: str | None) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


async def _community_market_compare(
    *,
    product_key: str,
    deal_price: int | None,
    deal_seller: str | None,
    deal_url: str | None,
) -> dict:
    """동일 product_key의 커뮤니티 관측을 판매처별 최저가로 묶는다."""
    if not product_key:
        return {
            "enabled": True,
            "mode": "community",
            "items": [],
            "note": "비교할 가격 이력이 아직 없습니다.",
            "fetched_at": None,
        }
    cur = await _db().execute(
        """
        SELECT
          COALESCE(NULLIF(TRIM(seller), ''), '기타') AS mall,
          MIN(price) AS price,
          COUNT(*) AS cnt,
          MAX(observed_at) AS last_seen
        FROM price_points
        WHERE product_key=?
          AND IFNULL(source, '') != 'naver'
        GROUP BY mall
        ORDER BY price ASC
        LIMIT 12
        """,
        (product_key,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    items: list[dict] = []
    deal_norm = _norm_mall(deal_seller)
    if deal_price:
        label = f"이 딜 · {deal_seller}" if deal_seller else "이 딜 · 현재"
        items.append(
            {
                "mall": label,
                "title": label,
                "price": int(deal_price),
                "url": deal_url,
                "is_deal": True,
                "count": 1,
                "similarity": 1.0,
            }
        )
    for row in rows:
        mall = row.get("mall") or "기타"
        if deal_norm and _norm_mall(mall) == deal_norm:
            continue
        items.append(
            {
                "mall": mall,
                "title": mall,
                "price": int(row["price"]),
                "url": None,
                "is_deal": False,
                "count": int(row.get("cnt") or 0),
                "similarity": 1.0,
                "last_seen": row.get("last_seen"),
            }
        )
    items.sort(key=lambda x: (0 if x.get("is_deal") else 1, x.get("price") or 10**12))
    if not items:
        note = "비교할 가격 이력이 아직 없습니다."
    elif len(items) == 1:
        note = "다른 판매처 이력이 아직 적어, 현재 딜 가격만 표시합니다."
    else:
        note = "커뮤니티에 올라온 동일 상품의 판매처별 최저가입니다."
    return {
        "enabled": True,
        "mode": "community",
        "items": items,
        "note": note,
        "fetched_at": None,
    }


async def _distinct(column: str) -> list[str]:
    cur = await _db().execute(
        f"SELECT DISTINCT {column} AS v FROM deals WHERE {column} IS NOT NULL AND {column}!='' ORDER BY v"
    )
    return [r["v"] for r in await cur.fetchall()]


async def _category_counts() -> tuple[dict[str, int], int]:
    cur = await _db().execute("SELECT COUNT(*) AS c FROM deals")
    total = int((await cur.fetchone())["c"] or 0)
    cur = await _db().execute(
        """
        SELECT COALESCE(NULLIF(TRIM(category), ''), '기타') AS cat, COUNT(*) AS c
        FROM deals
        GROUP BY cat
        """
    )
    counts = {str(r["cat"]): int(r["c"] or 0) for r in await cur.fetchall()}
    return counts, total


async def _distinct_sources() -> list[str]:
    cur = await _db().execute("SELECT DISTINCT source AS v FROM posts ORDER BY v")
    return [r["v"] for r in await cur.fetchall()]
