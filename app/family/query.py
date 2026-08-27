from __future__ import annotations

import calendar
from datetime import date

from app.family.parse import decode_sale_row, sale_status

CATEGORIES = ["패션의류", "뷰티", "잡화", "유아", "식품", "기타"]


def parse_cats(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [v for v in values if v in CATEGORIES]


async def list_sales(db, categories: list[str] | None = None, entry_only: bool = False, include_ended: bool = False):
    sql = "SELECT * FROM family_sales WHERE 1=1"
    params: list = []
    if entry_only:
        sql += " AND has_entry_code=1"
    if not include_ended:
        sql += " AND (end_date IS NULL OR end_date >= date('now', '+9 hours'))"
    sql += " ORDER BY has_entry_code DESC, COALESCE(start_date, '9999') ASC, id DESC"
    cur = await db.execute(sql, params)
    rows = [decode_sale_row(dict(r)) for r in await cur.fetchall()]
    today = date.today()
    out = []
    seen_groups: set[int] = set()
    for r in rows:
        r["status"] = sale_status(r.get("start_date"), r.get("end_date"), today)
        r["brands_label"] = " / ".join(r.get("brand_names") or []) or "-"
        r["cats_label"] = ", ".join(r.get("categories") or [])
        if categories:
            if not set(r.get("categories") or []) & set(categories):
                continue
        gid = r.get("group_id") or r["id"]
        if gid in seen_groups:
            continue
        seen_groups.add(gid)
        out.append(r)
    return out


async def get_sale(db, sale_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM family_sales WHERE id=?", (sale_id,))
    row = await cur.fetchone()
    if not row:
        return None
    sale = decode_sale_row(dict(row))
    sale["status"] = sale_status(sale.get("start_date"), sale.get("end_date"))
    sale["brands_label"] = " / ".join(sale.get("brand_names") or []) or "-"
    if sale.get("group_id"):
        cur = await db.execute(
            "SELECT id, source_name, source_url, title FROM family_sales WHERE group_id=? ORDER BY id",
            (sale["group_id"],),
        )
        sale["siblings"] = [dict(r) for r in await cur.fetchall()]
    else:
        sale["siblings"] = []
    return sale


def month_grid(year: int, month: int, sales: list[dict]) -> dict:
    cal = calendar.Calendar(firstweekday=6)
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        days = []
        for d in week:
            overlapping = [
                s
                for s in sales
                if s.get("start_date")
                and s.get("end_date")
                and s["start_date"][:10] <= d.isoformat() <= s["end_date"][:10]
            ]
            days.append(
                {
                    "date": d.isoformat(),
                    "day": d.day,
                    "in_month": d.month == month,
                    "sales": overlapping,
                    "count": len(overlapping),
                    "has_code": any(s.get("has_entry_code") for s in overlapping),
                }
            )
        weeks.append(days)
    return {"year": year, "month": month, "weeks": weeks, "label": f"{year}년 {month}월"}


def parse_year_month(year: int | None, month: int | None) -> tuple[int, int]:
    today = date.today()
    y = year or today.year
    m = month or today.month
    if m < 1 or m > 12:
        m = today.month
    return y, m
