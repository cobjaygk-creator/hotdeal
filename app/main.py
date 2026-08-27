from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import COLLECT_INTERVAL_MINUTES, PPOMPPU_INTERVAL_SECONDS
from app.db import connect, get_meta
from app.events import EventHub
from app.http_client import PoliteClient
from app.pipeline import collect_and_process
from app.sources.registry import get_sources
from app.util.timeparse import format_kst

log = logging.getLogger("hotdeal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["kst"] = format_kst
STATIC_DIR = Path(__file__).parent / "static"

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["db"] = await connect()
    state["http"] = PoliteClient()
    state["hub"] = EventHub()
    state["collect_lock"] = asyncio.Lock()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _scheduled_collect,
        "interval",
        seconds=PPOMPPU_INTERVAL_SECONDS,
        id="collect_ppomppu",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        _scheduled_collect_others,
        "interval",
        minutes=COLLECT_INTERVAL_MINUTES,
        id="collect_others",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    state["scheduler"] = scheduler
    try:
        yield
    finally:
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
):
    stats = await _stats()
    deals = await _list_deals(grade=grade, seller=seller, source=source, limit=200)
    sellers = await _distinct("seller")
    sources = await _distinct_sources()
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "deals": deals,
            "grade": grade or "",
            "seller": seller or "",
            "source": source or "",
            "sellers": sellers,
            "sources": sources,
        },
    )


@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def deal_detail(request: Request, deal_id: int):
    deal = await _get_deal(deal_id)
    if not deal:
        raise HTTPException(404, "deal not found")
    posts = await _deal_posts(deal_id)
    history = await _price_history(deal["product_key"])
    return TEMPLATES.TemplateResponse(
        "deal.html",
        {"request": request, "deal": deal, "posts": posts, "history": history},
    )


@app.get("/api/deals")
async def api_deals(
    grade: str | None = None,
    seller: str | None = None,
    source: str | None = None,
    limit: int = Query(100, le=500),
):
    return await _list_deals(grade=grade, seller=seller, source=source, limit=limit)


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
    names = [source] if source else None
    summary = await _run_collect(names)
    return JSONResponse(summary)


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
    return {
        "posts": posts,
        "deals": deals,
        "today_hot": today_hot,
        "strong": strong,
        "last_collect_at": last,
    }


async def _list_deals(grade=None, seller=None, source=None, limit=100) -> list[dict]:
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
    sql += " GROUP BY d.id ORDER BY COALESCE(d.last_scored_at, d.last_seen_at) DESC, d.id DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(sql, params)
    return [dict(r) for r in await cur.fetchall()]


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
