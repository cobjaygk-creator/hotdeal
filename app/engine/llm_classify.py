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
import re

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


def _model_tag(model: str = LLM_MODEL) -> str:
    """Short stable tag, e.g. claude-sonnet-5 -> sonnet-5, ...haiku-4-5-2025... -> haiku-4-5."""
    m = re.sub(r"^claude-", "", (model or "").strip().lower())
    m = re.sub(r"-\d{6,}.*$", "", m)  # drop a trailing yyyymmdd[-suffix]
    return m or "llm"


# deals.category_source once the model has classified a row. Encodes the model
# so swapping LLM_MODEL (or landing a prompt fix behind a new tag) makes the
# background sweep re-open every row an *older* model pinned — no manual reset.
_SRC = "llm:" + _model_tag()

_API_URL = "https://api.anthropic.com/v1/messages"
_VALID = set(CATEGORIES)

_SYSTEM = (
    "너는 한국 온라인 쇼핑 핫딜 상품명을 아래 9개 카테고리 중 하나로 분류한다.\n"
    "식품: 먹거나 마시는 모든 것 — 과자·라면·음료·정육·수산·과일·건강기능식품·"
    "커피원두·밀키트·외식쿠폰(치킨/버거/피자 기프티콘).\n"
    "생활: 세제·화장품·스킨케어·바디·헤어·구강·위생용품·휴지·반려동물용품·문구·"
    "주방잡화·수납·캠핑·자동차용품.\n"
    "PC: 노트북(그램·갤럭시북·아이디어패드 등 라인명 포함)·데스크탑·모니터·그래픽카드·"
    "CPU·SSD·RAM·키보드·마우스·스마트폰·태블릿·이어폰·헤드폰·스마트워치·충전기·"
    "보조배터리·공유기·NAS.\n"
    "가전: TV·냉장고·세탁기·청소기·에어컨·공기청정기·에어프라이어·전기밥솥·"
    "커피머신·안마의자·드라이어·면도기·전동칫솔.\n"
    "의류: 옷·신발(운동화·구두·샌들)·가방·모자·양말·속옷·잡화·액세서리.\n"
    "유아: 기저귀·분유·이유식·유모차·카시트·아기옷·아기용품.\n"
    "게임: 콘솔(스위치·PS5·Xbox)·게임 타이틀·DLC·게임패드·기프트카드(스팀/닌텐도).\n"
    "도서: 책·전집·문제집·잡지·전자책.\n"
    "기타: 위 8개 중 어디에도 정말 해당하지 않을 때만. (상품권·복권·정체불명 묶음 등)\n"
    "조금이라도 맞는 카테고리가 있으면 절대 기타로 보내지 마라. "
    "브랜드/라인명(그램, 에어맥스, 갤럭시북 등)도 제품 종류로 판단하라. "
    "근거는 쓰지 말고 분류만 한다."
)
_FEWSHOT = (
    "예: LG 그램 14 노트북 → PC / 나이키 에어맥스 신발 → 의류 / "
    "해태 에이스 카라멜 → 식품 / 버거킹 와퍼 세트 → 식품 / "
    "발 각질 패치 50매 → 생활 / 다우니 섬유유연제 → 생활 / "
    "닌텐도 스위치 기프트카드 → 게임 / 삼성 갤럭시탭 → PC\n"
)
_INSTRUCT = (
    "아래 상품을 분류해라. 각 줄은 `번호<TAB>정보` 형식이다.\n"
    'JSON 객체 하나로만 답해라: {"번호": "카테고리", ...}. 다른 텍스트·설명 금지.\n'
    "각 번호는 입력에 준 번호를 그대로 쓴다. "
    "카테고리는 반드시 " + "/".join(CATEGORIES) + " 중 하나.\n"
    + _FEWSHOT
    + "\n"
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


async def reclassify_pending(
    conn, *, limit: int | None = None, reset: str | None = None
) -> dict:
    """Background sweep: LLM-classify deals the keyword pass left weak/unset.

    reset="기타"  -> re-open only deals an earlier LLM run parked in 기타
    reset="all"  -> re-open every deal an earlier LLM run touched
    (both flip category_source back to NULL so the sweep picks them up again;
    'manual' overrides are never reset. Swapping LLM_MODEL already re-opens
    rows an older model pinned, so reset is only for forcing a same-model redo.)
    """
    if not LLM_CLASSIFY_ENABLED:
        return {"skipped": True, "reason": "LLM_CLASSIFY_ENABLED off", "checked": 0, "changed": 0}
    if reset == "all":
        await conn.execute(
            "UPDATE deals SET category_source = NULL WHERE category_source LIKE 'llm%'"
        )
        await conn.commit()
    elif reset == "기타":
        await conn.execute(
            "UPDATE deals SET category_source = NULL "
            "WHERE category_source LIKE 'llm%' AND (category = '기타' OR category IS NULL)"
        )
        await conn.commit()
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
        WHERE IFNULL(d.category_source, '') NOT IN ('manual', ?)
        ORDER BY
          CASE WHEN d.category IS NULL OR d.category = '기타' THEN 0 ELSE 1 END,
          d.last_seen_at DESC
        LIMIT ?
        """,
        (_SRC, cap),
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
        # Fallback: model ignored our ids and answered 1..N by position.
        chunk_ids = {r["id"] for r in chunk}
        if not (result.keys() & chunk_ids) and set(result) <= set(
            range(1, len(chunk) + 1)
        ):
            result = {chunk[k - 1]["id"]: v for k, v in result.items()}
        for r in chunk:
            new = result.get(r["id"])
            if not new:
                continue  # unmarked -> retried next tick
            checked += 1
            if new != (r.get("category") or ""):
                await conn.execute(
                    "UPDATE deals SET category = ?, category_source = ? WHERE id = ?",
                    (new, _SRC, r["id"]),
                )
                changed += 1
            else:
                await conn.execute(
                    "UPDATE deals SET category_source = ? WHERE id = ?",
                    (_SRC, r["id"]),
                )
    await conn.commit()

    summary = {
        "skipped": False,
        "checked": checked,
        "changed": changed,
        "model": _SRC,
        "at": utcnow_iso(),
    }
    await set_meta(conn, "last_llm_classify", json.dumps(summary, ensure_ascii=False))
    await conn.commit()
    log.info("llm classify checked=%s changed=%s model=%s", checked, changed, _SRC)
    return summary
