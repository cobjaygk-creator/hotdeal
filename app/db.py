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

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    email TEXT,
    username TEXT,
    password_hash TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    notify_channel TEXT,
    notify_target TEXT,
    created_at TEXT NOT NULL,
    last_login_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_identities (
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    email TEXT,
    PRIMARY KEY (provider, subject)
);

CREATE TABLE IF NOT EXISTS user_bookmarks (
    user_id INTEGER NOT NULL,
    deal_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, deal_id)
);

CREATE TABLE IF NOT EXISTS user_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    keyword TEXT NOT NULL,
    min_grade TEXT NOT NULL DEFAULT '핫딜',
    created_at TEXT NOT NULL,
    UNIQUE(user_id, keyword)
);

CREATE TABLE IF NOT EXISTS deal_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL,
    parent_id INTEGER,
    user_id INTEGER,
    nickname TEXT NOT NULL,
    pin_hash TEXT,
    client_key TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS deal_reactions (
    deal_id INTEGER NOT NULL,
    client_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (deal_id, client_key, kind)
);

CREATE TABLE IF NOT EXISTS deal_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT,
    client_key TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_posted ON posts(posted_at);
CREATE TABLE IF NOT EXISTS market_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL,
    mall TEXT NOT NULL,
    title TEXT NOT NULL,
    price INTEGER NOT NULL,
    url TEXT,
    product_id TEXT,
    similarity REAL,
    fetched_at TEXT NOT NULL,
    UNIQUE(product_key, mall, product_id)
);

CREATE INDEX IF NOT EXISTS idx_deal_comments_deal ON deal_comments(deal_id, id);
CREATE INDEX IF NOT EXISTS idx_deal_reactions_deal ON deal_reactions(deal_id, kind);
CREATE INDEX IF NOT EXISTS idx_deal_reports_created ON deal_reports(created_at);
CREATE INDEX IF NOT EXISTS idx_market_listings_key ON market_listings(product_key, fetched_at);
CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source, source_post_id);
CREATE INDEX IF NOT EXISTS idx_deals_seen ON deals(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_deals_grade ON deals(grade);
CREATE INDEX IF NOT EXISTS idx_deals_key ON deals(product_key);
CREATE INDEX IF NOT EXISTS idx_price_key_time ON price_points(product_key, observed_at);
CREATE TABLE IF NOT EXISTS amazon_jp_deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asin TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    yen_price INTEGER NOT NULL,
    original_yen INTEGER,
    discount_rate REAL NOT NULL,
    image_url TEXT,
    amazon_url TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    source_updated_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_family_dates ON family_sales(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_family_group ON family_sales(group_id);
CREATE INDEX IF NOT EXISTS idx_amazon_jp_active ON amazon_jp_deals(active, discount_rate);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def connect(path: Path | None = None) -> aiosqlite.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = path or DATABASE_PATH
    conn = await aiosqlite.connect(db_path, timeout=30.0)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=30000")
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
    if "body_html" not in post_cols:
        await conn.execute("ALTER TABLE posts ADD COLUMN body_html TEXT")

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

    # Drop Naver ads / oauth / fixer junk that slipped in as "shop" links.
    junk_malls = await get_meta(conn, "cleaned_junk_mall_urls_v1")
    if junk_malls != "1":
        await conn.execute(
            """
            UPDATE deals
            SET mall_url=NULL
            WHERE lower(mall_url) LIKE '%saedu.naver.com%'
               OR lower(mall_url) LIKE '%searchad.naver.com%'
               OR lower(mall_url) LIKE '%adcr.naver.com%'
               OR lower(mall_url) LIKE '%nid.naver.com%'
               OR lower(mall_url) LIKE '%auth.naver.com%'
               OR lower(mall_url) LIKE '%api.fixer.io%'
            """
        )
        await set_meta(conn, "cleaned_junk_mall_urls_v1", "1")

    junk_malls_v2 = await get_meta(conn, "cleaned_junk_mall_urls_v2")
    if junk_malls_v2 != "1":
        await conn.execute(
            """
            UPDATE deals
            SET mall_url=NULL
            WHERE lower(mall_url) LIKE '%dajooda.com%'
            """
        )
        await set_meta(conn, "cleaned_junk_mall_urls_v2", "1")

    try:
        await _unwrap_wrapper_mall_urls(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("mall wrapper unwrap skipped")

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
    try:
        await _ensure_auth_tables(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("auth tables failed")
    try:
        await _ensure_amazon_jp_table(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("amazon jp table failed")
    try:
        await _ensure_comment_tables(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("comment tables failed")
    try:
        await _ensure_market_tables(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("market tables failed")


async def _ensure_auth_tables(conn: aiosqlite.Connection) -> None:
    await conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL,
            email TEXT,
            username TEXT,
            password_hash TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            notify_channel TEXT,
            notify_target TEXT,
            created_at TEXT NOT NULL,
            last_login_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS oauth_identities (
            provider TEXT NOT NULL,
            subject TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            email TEXT,
            PRIMARY KEY (provider, subject)
        );
        CREATE TABLE IF NOT EXISTS user_bookmarks (
            user_id INTEGER NOT NULL,
            deal_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, deal_id)
        );
        CREATE TABLE IF NOT EXISTS user_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            keyword TEXT NOT NULL,
            min_grade TEXT NOT NULL DEFAULT '핫딜',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, keyword)
        );
        """
    )
    cur = await conn.execute("PRAGMA table_info(alert_subs)")
    cols = {row[1] for row in await cur.fetchall()}
    if "user_id" not in cols:
        await conn.execute("ALTER TABLE alert_subs ADD COLUMN user_id INTEGER")
    cur = await conn.execute("PRAGMA table_info(users)")
    user_cols = {row[1] for row in await cur.fetchall()}
    for name, decl in (
        ("email", "TEXT"),
        ("notify_channel", "TEXT"),
        ("notify_target", "TEXT"),
        ("display_name", "TEXT"),
        ("created_at", "TEXT"),
        ("last_login_at", "TEXT"),
        ("username", "TEXT"),
        ("password_hash", "TEXT"),
        ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in user_cols:
            await conn.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username "
        "ON users(username) WHERE username IS NOT NULL AND TRIM(username) != ''"
    )
    try:
        from app.engine.auth import ensure_local_admin

        await ensure_local_admin(conn)
    except Exception:
        logging.getLogger("hotdeal").exception("local admin seed failed")


async def _ensure_comment_tables(conn: aiosqlite.Connection) -> None:
    await conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS deal_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id INTEGER NOT NULL,
            parent_id INTEGER,
            user_id INTEGER,
            nickname TEXT NOT NULL,
            pin_hash TEXT,
            client_key TEXT,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS deal_reactions (
            deal_id INTEGER NOT NULL,
            client_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (deal_id, client_key, kind)
        );
        CREATE TABLE IF NOT EXISTS deal_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            detail TEXT,
            client_key TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_deal_comments_deal ON deal_comments(deal_id, id);
        CREATE INDEX IF NOT EXISTS idx_deal_reactions_deal ON deal_reactions(deal_id, kind);
        CREATE INDEX IF NOT EXISTS idx_deal_reports_created ON deal_reports(created_at);
        """
    )


async def _ensure_market_tables(conn: aiosqlite.Connection) -> None:
    await conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS market_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT NOT NULL,
            mall TEXT NOT NULL,
            title TEXT NOT NULL,
            price INTEGER NOT NULL,
            url TEXT,
            product_id TEXT,
            similarity REAL,
            fetched_at TEXT NOT NULL,
            UNIQUE(product_key, mall, product_id)
        );
        CREATE INDEX IF NOT EXISTS idx_market_listings_key
            ON market_listings(product_key, fetched_at);
        """
    )


async def _ensure_amazon_jp_table(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS amazon_jp_deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asin TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            yen_price INTEGER NOT NULL,
            original_yen INTEGER,
            discount_rate REAL NOT NULL,
            image_url TEXT,
            amazon_url TEXT NOT NULL,
            source TEXT NOT NULL,
            source_url TEXT,
            source_updated_at TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_amazon_jp_active ON amazon_jp_deals(active, discount_rate)"
    )


async def _unwrap_wrapper_mall_urls(conn: aiosqlite.Connection) -> None:
    from app.parse.links import extract_shop_url

    cur = await conn.execute(
        """
        SELECT id, mall_url FROM deals
        WHERE mall_url LIKE '%unsafelink.com%'
           OR mall_url LIKE '%href.li/%'
        """
    )
    rows = [dict(r) for r in await cur.fetchall()]
    changed = 0
    for row in rows:
        fixed = extract_shop_url(row["mall_url"])
        if not fixed or fixed == row["mall_url"]:
            continue
        await conn.execute(
            "UPDATE deals SET mall_url=? WHERE id=?",
            (fixed, row["id"]),
        )
        changed += 1
    if changed:
        await conn.commit()
        logging.getLogger("hotdeal").info("unwrapped %s mall wrapper urls", changed)


async def _backfill_categories(conn: aiosqlite.Connection) -> None:
    from app.engine.category import classify

    cur = await conn.execute("SELECT id, product_name, seller, category FROM deals")
    rows = await cur.fetchall()
    for row in rows:
        cat = classify(row["product_name"], row["seller"])
        if cat != (row["category"] or ""):
            await conn.execute(
                "UPDATE deals SET category=? WHERE id=?",
                (cat, row["id"]),
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
            title=COALESCE(NULLIF(excluded.title, ''), posts.title),
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


async def upsert_amazon_jp_deal(conn: aiosqlite.Connection, deal: dict) -> tuple[int, bool]:
    now = utcnow_iso()
    cur = await conn.execute(
        "SELECT id FROM amazon_jp_deals WHERE asin=?",
        (deal["asin"],),
    )
    existing = await cur.fetchone()
    inserted = existing is None
    await conn.execute(
        """
        INSERT INTO amazon_jp_deals(
            asin, title, yen_price, original_yen, discount_rate, image_url,
            amazon_url, source, source_url, source_updated_at,
            first_seen_at, last_seen_at, active
        ) VALUES(
            :asin, :title, :yen_price, :original_yen, :discount_rate, :image_url,
            :amazon_url, :source, :source_url, :source_updated_at,
            :first_seen_at, :last_seen_at, :active
        )
        ON CONFLICT(asin) DO UPDATE SET
            title=excluded.title,
            yen_price=excluded.yen_price,
            original_yen=COALESCE(excluded.original_yen, amazon_jp_deals.original_yen),
            discount_rate=excluded.discount_rate,
            image_url=COALESCE(excluded.image_url, amazon_jp_deals.image_url),
            amazon_url=excluded.amazon_url,
            source=excluded.source,
            source_url=excluded.source_url,
            source_updated_at=COALESCE(excluded.source_updated_at, amazon_jp_deals.source_updated_at),
            last_seen_at=excluded.last_seen_at,
            active=1
        """,
        {
            "asin": deal["asin"],
            "title": deal["title"],
            "yen_price": int(deal["yen_price"]),
            "original_yen": deal.get("original_yen"),
            "discount_rate": float(deal["discount_rate"]),
            "image_url": deal.get("image_url"),
            "amazon_url": deal["amazon_url"],
            "source": deal.get("source") or "mottoku",
            "source_url": deal.get("source_url"),
            "source_updated_at": deal.get("source_updated_at"),
            "first_seen_at": deal.get("first_seen_at") or now,
            "last_seen_at": deal.get("last_seen_at") or now,
            "active": 1 if deal.get("active", 1) else 0,
        },
    )
    cur = await conn.execute("SELECT id FROM amazon_jp_deals WHERE asin=?", (deal["asin"],))
    row = await cur.fetchone()
    return int(row["id"]), inserted


