"""LLM-backed category re-classification, layered over the keyword classifier.

`app.engine.category.classify` still runs inline at collect time so every card
has a category immediately. This module re-checks deals in the background with
one small batched LLM call and overwrites `deals.category` when the keyword
guess was weak (기타) or wrong. `deals.category_source` tracks provenance so a
deal is classified by the LLM at most once (until a human marks it `manual`).
"""
from __future__ import annotations

import json
import logging

import httpx

from app.config import (
    ANTHROPIC_API_KEY,
    LLM_CLASSIFY_BATCH,
    LLM_CLASSIFY_ENABLED,
    LLM_CLASSIFY_PER_TICK,
    LLM_MODEL,
)
from app.db import set_meta, utcnow_iso
from app.engine.category import CATEGORIES

log = logging.getLogger("hotdeal.llm_classify")

_API_URL = "https://api.anthropic.com/v1/messages"
_VALID = set(CATEGORIES)

_SYSTEM = (
    "너는 한국 온라인 쇼핑 핫딜 상품을 카테고리로 분류한다. "
    "카테고리는 정확히 다음 9개 중 하나다: " + ", ".join(CATEGORIES) + ". "
    "제품명이 애매하면 주된 용도로 판단한다. 신발/의류/가방은 '의류', "
    "먹는 것은 '식품', 세제·화장품·반려동물·문구는 '생활'. "
    "근거를 쓰지 말고 분류만 한다."
)
_INSTRUCT = (
    "아래 상품을 분류해라. 각 줄은 `번호<TAB>정보` 형식이다.\n"
    'JSON 객체 하나로만 답해라: {"번호": "카테고리", ...}. 다른 텍스트 금지.\n'
    "카테고리는 반드시 " + "/".join(CATEGORIES) + " 중 하나.\n\n"
)


def _parse_response(text: str) -> dict[int, str]:
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            key = int(str(k).strip())
        except (TypeError, ValueError):
            continue
        cat = str(v).strip()
        if cat in _VALID:
            out[key] = cat
    return out


async def _call_api(prompt: str) -> dict[int, str]:
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "max_tokens": 1024,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    text = "".join(
        blk.get("text", "")
        for blk in data.get("content", [])
        if blk.get("type") == "text"
    )
    return _parse_response(text)


def _item_line(item: dict) -> str:
    parts = [
        str(x)
        for x in (item.get("seller"), item.get("title"), item.get("source_category"))
        if x
    ]
    return f"{item['id']}\t{' | '.join(parts)[:200]}"


async def classify_batch(items: list[dict]) -> dict[int, str]:
    """items: [{id, title, seller?, source_category?}] -> {id: category}.

    Missing / invalid ids in the response are simply omitted; the caller keeps
    the existing keyword category for those.
    """
    if not items or not LLM_CLASSIFY_ENABLED:
        return {}
    prompt = _INSTRUCT + "\n".join(_item_line(it) for it in items)
    try:
        return await _call_api(prompt)
    except Exception as exc:  # noqa: BLE001
        log.warning("llm classify call failed: %s", exc)
        return {}


def _source_category(raw_json) -> str | None:
    if isinstance(raw_json, str):
        try:
            raw_json = json.loads(raw_json)
        except (TypeError, ValueError):
            return None
    if isinstance(raw_json, dict):
        val = raw_json.get("source_category")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


async def reclassify_pending(conn, *, limit: int | None = None) -> dict:
    """Background sweep: LLM-classify deals the keyword pass left weak/unset."""
    if not LLM_CLASSIFY_ENABLED:
        return {"skipped": True, "reason": "LLM_CLASSIFY_ENABLED off", "checked": 0, "changed": 0}
    cap = max(1, limit or LLM_CLASSIFY_PER_TICK)
    cur = await conn.execute(
        """
        SELECT d.id, d.product_name, d.seller, d.category,
               (
                 SELECT p.raw_json FROM deal_posts dp
                 JOIN posts p ON p.id = dp.post_id
                 WHERE dp.deal_id = d.id
                 ORDER BY p.id LIMIT 1
               ) AS raw_json
        FROM deals d
        WHERE IFNULL(d.category_source, '') NOT IN ('llm', 'manual')
        ORDER BY
          CASE WHEN d.category IS NULL OR d.category = '기타' THEN 0 ELSE 1 END,
          d.last_seen_at DESC
        LIMIT ?
        """,
        (cap,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    if not rows:
        return {"skipped": False, "checked": 0, "changed": 0}

    checked = 0
    changed = 0
    for i in range(0, len(rows), LLM_CLASSIFY_BATCH):
        chunk = rows[i : i + LLM_CLASSIFY_BATCH]
        items = [
            {
                "id": r["id"],
                "title": r["product_name"],
                "seller": r.get("seller"),
                "source_category": _source_category(r.get("raw_json")),
            }
            for r in chunk
        ]
        result = await classify_batch(items)
        if not result:
            # API failure for this chunk: leave rows unmarked, retry next tick.
            continue
        for r in chunk:
            new = result.get(r["id"])
            if not new:
                continue  # unmarked -> retried next tick
            checked += 1
            if new != (r.get("category") or ""):
                await conn.execute(
                    "UPDATE deals SET category = ?, category_source = 'llm' WHERE id = ?",
                    (new, r["id"]),
                )
                changed += 1
            else:
                await conn.execute(
                    "UPDATE deals SET category_source = 'llm' WHERE id = ?",
                    (r["id"],),
                )
    await conn.commit()

    summary = {
        "skipped": False,
        "checked": checked,
        "changed": changed,
        "at": utcnow_iso(),
    }
    await set_meta(conn, "last_llm_classify", json.dumps(summary, ensure_ascii=False))
    await conn.commit()
    log.info("llm classify checked=%s changed=%s", checked, changed)
    return summary
