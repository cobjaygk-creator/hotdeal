from __future__ import annotations

import json
import logging
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
    last_scored_price INTEGER,
    category TEXT
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

CREATE TABLE IF NOT EXISTS alert_subs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    min_grade TEXT NOT NULL DEFAULT '핫딜',
    channel TEXT NOT NULL,
    target TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    origin TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL,
    UNIQUE(keyword, channel, target)
);

CREATE TABLE IF NOT EXISTS alert_sent (
    sub_id INTEGER NOT NULL,
    deal_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (sub_id, deal_id),
    FOREIGN KEY (sub_id) REFERENCES alert_subs(id)
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
    try:
        await conn.executescript(SCHEMA)
    except Exception:
        logging.getLogger("hotdeal").exception("schema apply failed; continuing with alters")
    await _ensure_columns(conn)
    await conn.commit()
    return conn


async def _ensure_columns(conn: aiosqlite.Connection) -> None:
    cur = await conn.execute("PRAGMA table_info(deals)")
    deal_cols = {row[1] for row in await cur.fetchall()}
    for name, decl in (
        ("shipping_fee", "INTEGER"),
        ("unit_price", "REAL"),
        ("deal_url", "TEXT"),
        ("mall_url", "TEXT"),
        ("thumbnail_url", "TEXT"),
        ("baseline_price", "INTEGER"),
        ("min_price", "INTEGER"),
        ("sample_count", "INTEGER"),
        ("discount_rate", "REAL"),
        ("score", "REAL"),
        ("grade", "TEXT"),
        ("status", "TEXT"),
        ("last_scored_at", "TEXT"),
        ("last_scored_price", "INTEGER"),
        ("category", "TEXT"),
    ):
        if name not in deal_cols:
            await conn.execute(f"ALTER TABLE deals ADD COLUMN {name} {decl}")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_deals_category ON deals(category)")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_subs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            min_grade TEXT NOT NULL DEFAULT '핫딜',
            channel TEXT NOT NULL,
            target TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            origin TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            UNIQUE(keyword, channel, target)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_sent (
            sub_id INTEGER NOT NULL,
            deal_id INTEGER NOT NULL,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (sub_id, deal_id)
        )
        """
    )

    cur = await conn.execute("PRAGMA table_info(posts)")
    post_cols = {row[1] for row in await cur.fetchall()}
    if "thumbnail_url" not in post_cols:
        await conn.execute("ALTER TABLE posts ADD COLUMN thumbnail_url TEXT")

    try:
        cleaned = await get_meta(conn, "cleaned_sub1000_prices")
        if cleaned != "1":
            await conn.execute("DELETE FROM price_points WHERE price < 1000")
            await conn.execute(
                """
                UPDATE deals
                SET price=NULL, unit_price=NULL, discount_rate=NULL, score=0,
                    grade='확인필요', status='needs_review', last_scored_price=NULL
                WHERE price IS NOT NULL AND price < 1000
                """
            )
            await set_meta(conn, "cleaned_sub1000_prices", "1")
    except Exception:
        logging.getLogger("hotdeal").exception("price cleanup skipped")

    # Clear display-truncated mall links that 404 when clicked (… / ...).
    bad_malls = await get_meta(conn, "cleaned_truncated_mall_urls")
    if bad_malls != "1":
        await conn.execute(
            """
            UPDATE deals
            SET mall_url=NULL
            WHERE mall_url LIKE '%…%'
               OR mall_url LIKE '%...%'
            """
        )
        await set_meta(conn, "cleaned_truncated_mall_urls", "1")

    try:
        await _backfill_categories(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("category backfill failed")
    try:
        await _ensure_fts(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("fts setup failed")
    try:
        from app.engine.alerts import seed_env_subs

        await seed_env_subs(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("alert seed failed")


async def _backfill_categories(conn: aiosqlite.Connection) -> None:
    from app.engine.category import classify

    cur = await conn.execute(
        "SELECT id, product_name, seller FROM deals WHERE category IS NULL OR category=''"
    )
    rows = await cur.fetchall()
    for row in rows:
        await conn.execute(
            "UPDATE deals SET category=? WHERE id=?",
            (classify(row["product_name"], row["seller"]), row["id"]),
        )


async def _ensure_fts(conn: aiosqlite.Connection) -> None:
    try:
        await conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS deals_fts USING fts5(
                product_name,
                seller,
                content='deals',
                content_rowid='id',
                tokenize='unicode61'
            )
            """
        )
    except Exception:
        logging.getLogger("hotdeal").exception("fts table create failed")
        return
    try:
        await conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS deals_ai AFTER INSERT ON deals BEGIN
                INSERT INTO deals_fts(rowid, product_name, seller)
                VALUES (new.id, new.product_name, new.seller);
            END
            """
        )
        await conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS deals_ad AFTER DELETE ON deals BEGIN
                INSERT INTO deals_fts(deals_fts, rowid, product_name, seller)
                VALUES('delete', old.id, old.product_name, old.seller);
            END
            """
        )
        await conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS deals_au AFTER UPDATE ON deals BEGIN
                INSERT INTO deals_fts(deals_fts, rowid, product_name, seller)
                VALUES('delete', old.id, old.product_name, old.seller);
                INSERT INTO deals_fts(rowid, product_name, seller)
                VALUES (new.id, new.product_name, new.seller);
            END
            """
        )
    except Exception:
        logging.getLogger("hotdeal").exception("fts trigger create failed")
        return
    try:
        cur = await conn.execute("SELECT COUNT(*) AS n FROM deals")
        deals_n = int((await cur.fetchone())["n"])
        cur = await conn.execute("SELECT COUNT(*) AS n FROM deals_fts")
        fts_n = int((await cur.fetchone())["n"])
        if deals_n and fts_n != deals_n:
            await conn.execute("INSERT INTO deals_fts(deals_fts) VALUES('rebuild')")
    except Exception:
        logging.getLogger("hotdeal").exception("fts rebuild skipped")


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
                          votes, views, comments, collected_at, raw_json, thumbnail_url)
        VALUES(:source, :source_post_id, :url, :title, :body, :author, :posted_at,
               :votes, :views, :comments, :collected_at, :raw_json, :thumbnail_url)
        ON CONFLICT(source, source_post_id) DO UPDATE SET
            url=excluded.url,
            title=CASE
                WHEN length(COALESCE(excluded.title, '')) > length(COALESCE(posts.title, ''))
                THEN excluded.title ELSE posts.title END,
            body=COALESCE(excluded.body, posts.body),
            author=COALESCE(excluded.author, posts.author),
            posted_at=COALESCE(excluded.posted_at, posts.posted_at),
            votes=excluded.votes,
            views=excluded.views,
            comments=excluded.comments,
            collected_at=excluded.collected_at,
            raw_json=COALESCE(excluded.raw_json, posts.raw_json),
            thumbnail_url=COALESCE(excluded.thumbnail_url, posts.thumbnail_url)
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
            "thumbnail_url": post.get("thumbnail_url"),
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

