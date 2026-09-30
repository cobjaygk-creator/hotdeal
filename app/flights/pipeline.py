from __future__ import annotations

import logging
from app.config import FLIGHT_FEED_URL
from app.db import utcnow_iso

log = logging.getLogger(__name__)

async def collect_flight_offers(conn, client) -> dict:
    if not FLIGHT_FEED_URL:
        return {"enabled": False, "fetched": 0, "upserted": 0}
    result = await client.get(FLIGHT_FEED_URL, timeout=20.0, curl_fallback=False)
    if result.status >= 400:
        raise RuntimeError(f"flight feed status={result.status}")
    payload = result.json if hasattr(result, "json") else None
    if payload is None:
        import json
        payload = json.loads(result.text or "{}")
    rows = payload.get("offers", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("flight feed must be a JSON array or {offers: []}")
    now = utcnow_iso(); count = 0
    for item in rows[:1000]:
        if not isinstance(item, dict) or not item.get("origin") or not item.get("destination") or not item.get("price") or not item.get("booking_url") or not item.get("provider"):
            continue
        await conn.execute("""INSERT INTO flight_offers(provider,airline,origin,destination,depart_at,return_at,duration_days,seats,price,baggage,booking_url,thumbnail_url,collected_at,expires_at,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(provider,booking_url) DO UPDATE SET airline=excluded.airline,origin=excluded.origin,destination=excluded.destination,depart_at=excluded.depart_at,return_at=excluded.return_at,duration_days=excluded.duration_days,seats=excluded.seats,price=excluded.price,baggage=excluded.baggage,thumbnail_url=excluded.thumbnail_url,collected_at=excluded.collected_at,expires_at=excluded.expires_at,active=1""", (str(item["provider"]),item.get("airline"),str(item["origin"]),str(item["destination"]),item.get("depart_at"),item.get("return_at"),item.get("duration_days"),item.get("seats"),int(item["price"]),item.get("baggage"),str(item["booking_url"]),item.get("thumbnail_url"),now,item.get("expires_at")))
        count += 1
    await conn.commit()
    return {"enabled": True, "fetched": len(rows), "upserted": count, "at": now}
