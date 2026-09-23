"""Opt-in, list-only collection with durable request and cadence limits."""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.config import DATA_DIR
from app.http_client import soft_block_reason

URLS = {
    'https://arca.live/b/hotdeal': 'arca',
    'https://quasarzone.com/bbs/qb_saleinfo': 'quasarzone',
    'https://www.fmkorea.com/hotdeal': 'fmkorea',
    'https://coolenjoy.net/bbs/rss.php?bo_table=jirum': 'coolenjoy',
}


def enabled(source: str) -> bool:
    return (
        os.environ.get('BRIGHTDATA_ENABLED', '').lower() in ('1', 'true', 'yes')
        and source in os.environ.get('BRIGHTDATA_SOURCES', 'arca,quasarzone,fmkorea,coolenjoy').split(',')
    )


def enabled_host(url: str) -> bool:
    host = urlparse(url).hostname
    return any(host == urlparse(u).hostname and enabled(s) for u, s in URLS.items())


def reserve(source: str) -> bool:
    """Charge attempts before I/O; never refund failures or retry automatically.

    BEGIN IMMEDIATE serializes reservations across workers. The volume keeps
    counters and cooldowns across restarts. A missing volume must not be used
    for production: the cap covers this deployment, not the entire account.
    """
    limit = max(0, int(os.environ.get('BRIGHTDATA_MONTHLY_LIMIT', '4500')))
    interval = max(60, int(os.environ.get('BRIGHTDATA_INTERVAL_MINUTES', '60'))) * 60
    now = time.time()
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATA_DIR / 'brightdata-budget.db', timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS usage (month TEXT PRIMARY KEY, count INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS cadence (source TEXT PRIMARY KEY, last REAL NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        count = db.execute('SELECT count FROM usage WHERE month=?', (month,)).fetchone()
        if (count[0] if count else 0) >= limit:
            raise RuntimeError('Bright Data monthly request limit reached')
        last = db.execute('SELECT last FROM cadence WHERE source=?', (source,)).fetchone()
        if last and now - last[0] < interval:
            return False
        db.execute('INSERT INTO usage VALUES (?, 1) ON CONFLICT(month) DO UPDATE SET count=count+1', (month,))
        db.execute('INSERT INTO cadence VALUES (?, ?) ON CONFLICT(source) DO UPDATE SET last=excluded.last', (source, now))
    return True


async def fetch_posts(url, parse_fn):
    source = URLS[url]
    key = os.environ.get('BRIGHTDATA_API_KEY', '').strip()
    zone = os.environ.get('BRIGHTDATA_ZONE', '').strip()
    if not key or not zone:
        raise RuntimeError('Bright Data API key/zone not configured')
    if not reserve(source):
        return []
    payload = {'zone': zone, 'url': url, 'format': 'raw'}
    if source == 'fmkorea':
        payload.update(country='kr', render='true')
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        response = await client.post('https://api.brightdata.com/request',
            headers={'Authorization': f'Bearer {key}'}, json=payload)
    if response.status_code != 200:
        # Never include request headers, credentials or provider response body.
        raise RuntimeError(f'Bright Data HTTP {response.status_code}')
    reason = soft_block_reason(response.text)
    if reason:
        raise RuntimeError(f'Bright Data blocked: {reason}')
    posts = parse_fn(response.text)
    if not posts:
        raise RuntimeError('Bright Data returned no parsed posts')
    return posts
