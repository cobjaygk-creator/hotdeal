from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from app.config import DATABASE_PATH, DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_post_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    author TEXT,
    posted_at TEXT,
    votes INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    collected_at TEXT NOT NULL,
    raw_json TEXT,
    UNIQUE(source, source_post_id)
);

CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL,
    product_name TEXT NOT NULL,
    seller TEXT,
    price INTEGER,
    shipping_fee INTEGER,
    unit_price REAL,
    deal_url TEXT,
    mall_url TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    baseline_price INTEGER,
    min_price INTEGER,
    sample_count INTEGER DEFAULT 0,
    discount_rate REAL,
    score REAL DEFAULT 0,
    grade TEXT,
    status TEXT,
    last_scored_at TEXT,
    last_scored_price INTEGER
);

CREATE TABLE IF NOT EXISTS deal_posts (
    deal_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    PRIMARY KEY (deal_id, post_id),
    FOREIGN KEY (deal_id) REFERENCES deals(id),
    FOREIGN KEY (post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS price_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL,
    price INTEGER NOT NULL,
    unit_price REAL,
    seller TEXT,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    post_id INTEGER,
    UNIQUE(source, post_id)
);

CREATE TABLE IF NOT EXISTS family_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_post_id TEXT NOT NULL,
    title TEXT NOT NULL,
    brand_names TEXT NOT NULL,
    sale_type TEXT NOT NULL,
    sale_kind TEXT,
    start_date TEXT,
    end_date TEXT,
    location TEXT,
    has_entry_code INTEGER NOT NULL DEFAULT 0,
    entry_code TEXT,
    categories TEXT NOT NULL,
    discount_label TEXT,
    discount_max INTEGER,
    source_url TEXT NOT NULL,
    deal_url TEXT,
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    group_id INTEGER,
    UNIQUE(source_name, source_post_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_posted ON posts(posted_at);
CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source, source_post_id);
CREATE INDEX IF NOT EXISTS idx_deals_seen ON deals(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_deals_grade ON deals(grade);
CREATE INDEX IF NOT EXISTS idx_deals_key ON deals(product_key);
CREATE INDEX IF NOT EXISTS idx_price_key_time ON price_points(product_key, observed_at);
CREATE INDEX IF NOT EXISTS idx_family_dates ON family_sales(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_family_group ON family_sales(group_id);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def connect(path: Path | None = None) -> aiosqlite.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = path or DATABASE_PATH
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.executescript(SCHEMA)
    await _ensure_columns(conn)
    await conn.commit()
    return conn


async def _ensure_columns(conn: aiosqlite.Connection) -> None:
    cur = await conn.execute("PRAGMA table_info(deals)")
    cols = {row[1] for row in await cur.fetchall()}
    if "mall_url" not in cols:
        await conn.execute("ALTER TABLE deals ADD COLUMN mall_url TEXT")


async def set_meta(conn: aiosqlite.Connection, key: str, value: str) -> None:
    await conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


async def get_meta(conn: aiosqlite.Connection, key: str) -> str | None:
    cur = await conn.execute("SELECT value FROM meta WHERE key=?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else None


async def upsert_post(conn: aiosqlite.Connection, post: dict) -> tuple[int, bool]:
    raw = post.get("raw_json")
    if isinstance(raw, (dict, list)):
        raw = json.dumps(raw, ensure_ascii=False)
    cur = await conn.execute(
        "SELECT id FROM posts WHERE source=? AND source_post_id=?",
        (post["source"], str(post["source_post_id"])),
    )
    existing = await cur.fetchone()
    inserted = existing is None
    await conn.execute(
        """
        INSERT INTO posts(source, source_post_id, url, title, body, author, posted_at,
                          votes, views, comments, collected_at, raw_json)
        VALUES(:source, :source_post_id, :url, :title, :body, :author, :posted_at,
               :votes, :views, :comments, :collected_at, :raw_json)
        ON CONFLICT(source, source_post_id) DO UPDATE SET
            url=excluded.url,
            title=excluded.title,
            body=COALESCE(excluded.body, posts.body),
            author=COALESCE(excluded.author, posts.author),
            posted_at=COALESCE(excluded.posted_at, posts.posted_at),
            votes=excluded.votes,
            views=excluded.views,
            comments=excluded.comments,
            collected_at=excluded.collected_at,
            raw_json=COALESCE(excluded.raw_json, posts.raw_json)
        """,
        {
            "source": post["source"],
            "source_post_id": str(post["source_post_id"]),
            "url": post["url"],
            "title": post["title"],
            "body": post.get("body"),
            "author": post.get("author"),
            "posted_at": post.get("posted_at"),
            "votes": post.get("votes") or 0,
            "views": post.get("views") or 0,
            "comments": post.get("comments") or 0,
            "collected_at": post.get("collected_at") or utcnow_iso(),
            "raw_json": raw,
        },
    )
    cur = await conn.execute(
        "SELECT id FROM posts WHERE source=? AND source_post_id=?",
        (post["source"], str(post["source_post_id"])),
    )
    row = await cur.fetchone()
    return int(row["id"]), inserted


async def upsert_family_sale(conn: aiosqlite.Connection, sale: dict) -> tuple[int, bool]:
    now = utcnow_iso()
    cur = await conn.execute(
        "SELECT id FROM family_sales WHERE source_name=? AND source_post_id=?",
        (sale["source_name"], str(sale["source_post_id"])),
    )
    existing = await cur.fetchone()
    inserted = existing is None
    brands = sale.get("brand_names") or []
    cats = sale.get("categories") or []
    if isinstance(brands, list):
        brands = json.dumps(brands, ensure_ascii=False)
    if isinstance(cats, list):
        cats = json.dumps(cats, ensure_ascii=False)
    await conn.execute(
        """
        INSERT INTO family_sales(
            source_name, source_post_id, title, brand_names, sale_type, sale_kind,
            start_date, end_date, location, has_entry_code, entry_code, categories,
            discount_label, discount_max, source_url, deal_url, collected_at, updated_at, group_id
        ) VALUES(
            :source_name, :source_post_id, :title, :brand_names, :sale_type, :sale_kind,
            :start_date, :end_date, :location, :has_entry_code, :entry_code, :categories,
            :discount_label, :discount_max, :source_url, :deal_url, :collected_at, :updated_at, :group_id
        )
        ON CONFLICT(source_name, source_post_id) DO UPDATE SET
            title=excluded.title,
            brand_names=excluded.brand_names,
            sale_type=COALESCE(excluded.sale_type, family_sales.sale_type),
            sale_kind=COALESCE(excluded.sale_kind, family_sales.sale_kind),
            start_date=COALESCE(excluded.start_date, family_sales.start_date),
            end_date=COALESCE(excluded.end_date, family_sales.end_date),
            location=COALESCE(excluded.location, family_sales.location),
            has_entry_code=MAX(excluded.has_entry_code, family_sales.has_entry_code),
            entry_code=COALESCE(excluded.entry_code, family_sales.entry_code),
            categories=excluded.categories,
            discount_label=COALESCE(excluded.discount_label, family_sales.discount_label),
            discount_max=COALESCE(excluded.discount_max, family_sales.discount_max),
            source_url=excluded.source_url,
            deal_url=COALESCE(excluded.deal_url, family_sales.deal_url),
            updated_at=excluded.updated_at
        """,
        {
            "source_name": sale["source_name"],
            "source_post_id": str(sale["source_post_id"]),
            "title": sale["title"],
            "brand_names": brands,
            "sale_type": sale.get("sale_type") or "온라인",
            "sale_kind": sale.get("sale_kind"),
            "start_date": sale.get("start_date"),
            "end_date": sale.get("end_date"),
            "location": sale.get("location"),
            "has_entry_code": 1 if sale.get("has_entry_code") else 0,
            "entry_code": sale.get("entry_code"),
            "categories": cats,
            "discount_label": sale.get("discount_label"),
            "discount_max": sale.get("discount_max"),
            "source_url": sale["source_url"],
            "deal_url": sale.get("deal_url"),
            "collected_at": sale.get("collected_at") or now,
            "updated_at": now,
            "group_id": sale.get("group_id"),
        },
    )
    cur = await conn.execute(
        "SELECT id FROM family_sales WHERE source_name=? AND source_post_id=?",
        (sale["source_name"], str(sale["source_post_id"])),
    )
    row = await cur.fetchone()
    return int(row["id"]), inserted

