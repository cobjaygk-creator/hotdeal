"""Web Push (VAPID) delivery via pywebpush.

Dormant until VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY are set (WEBPUSH_ENABLED).
Real delivery needs HTTPS + a live browser push subscription, so this
path is only exercised end-to-end after deploy.
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.config import VAPID_PRIVATE_KEY, VAPID_SUBJECT, WEBPUSH_ENABLED

log = logging.getLogger("hotdeal.push")


def _send_sync(subscription_info: dict, payload: dict) -> int:
    from pywebpush import WebPushException, webpush

    try:
        resp = webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=3600,
        )
        return resp.status_code
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", 0)
        if status not in (404, 410):
            log.warning("web push failed: %s", exc)
        return status or 500


async def send_web_push(subscription_info: dict, payload: dict) -> int:
    """Returns the push service HTTP status. 404/410 => caller should
    drop the subscription."""
    if not WEBPUSH_ENABLED:
        return 0
    return await asyncio.to_thread(_send_sync, subscription_info, payload)
