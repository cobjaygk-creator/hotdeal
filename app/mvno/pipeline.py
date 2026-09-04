from __future__ import annotations

import logging

from app.config import MOYO_THEME_URLS
from app.db import set_meta, utcnow_iso
from app.mvno.moyo import fetch_plans

log = logging.getLogger(__name__)

_UPSERT = """
INSERT INTO mvno_plans(
    plan_id, name, mvno, mno, network, data_gb, data_unlimited, data_daily_gb,
    qos_kbps, voice_min, voice_unlimited, sms_unlimited, original_fee,
    discount_fee, discount_months, promo, promo_all, rating, signup_count,
    plan_url, brand_image, first_seen_at, last_seen_at, active
) VALUES(
    :plan_id, :name, :mvno, :mno, :network, :data_gb, :data_unlimited,
    :data_daily_gb, :qos_kbps, :voice_min, :voice_unlimited, :sms_unlimited,
    :original_fee, :discount_fee, :discount_months, :promo, :promo_all, :rating,
    :signup_count, :plan_url, :brand_image, :now, :now, 1
)
ON CONFLICT(plan_id) DO UPDATE SET
    name=excluded.name, mvno=excluded.mvno, mno=excluded.mno,
    network=excluded.network, data_gb=excluded.data_gb,
    data_unlimited=excluded.data_unlimited, data_daily_gb=excluded.data_daily_gb,
    qos_kbps=excluded.qos_kbps, voice_min=excluded.voice_min,
    voice_unlimited=excluded.voice_unlimited, sms_unlimited=excluded.sms_unlimited,
    original_fee=excluded.original_fee, discount_fee=excluded.discount_fee,
    discount_months=excluded.discount_months, promo=excluded.promo,
    promo_all=excluded.promo_all, rating=excluded.rating,
    signup_count=excluded.signup_count, plan_url=excluded.plan_url,
    brand_image=excluded.brand_image, last_seen_at=excluded.last_seen_at, active=1
"""


async def collect_mvno_plans(conn, client) -> dict:
    urls = tuple(MOYO_THEME_URLS) or None
    rows = await fetch_plans(client, urls)
    now = utcnow_iso()
    for row in rows:
        await conn.execute(_UPSERT, {**row, "now": now})
    seen_ids = [r["plan_id"] for r in rows]
    if seen_ids:
        ph = ",".join("?" * len(seen_ids))
        await conn.execute(
            f"UPDATE mvno_plans SET active=0 WHERE plan_id NOT IN ({ph})", seen_ids
        )
    await set_meta(conn, "last_mvno_collect_at", now)
    await conn.commit()
    log.info("mvno collect: %d event plans", len(rows))
    return {"fetched": len(rows), "at": now}
