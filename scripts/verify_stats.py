import sqlite3
from pathlib import Path

from app.parse.title import parse_title

out = Path("data/verify.txt")
c = sqlite3.connect("data/hotdeal.db")
c.row_factory = sqlite3.Row
lines = []

def w(s=""):
    lines.append(s)

w(f"posts={c.execute('select count(*) from posts').fetchone()[0]}")
w(f"price_points={c.execute('select count(*) from price_points').fetchone()[0]}")
w(f"deals={c.execute('select count(*) from deals').fetchone()[0]}")
w("grades:")
for r in c.execute("select grade, count(*) c from deals group by grade order by c desc"):
    w(f"  {r['grade']}: {r['c']}")
w("sources:")
for r in c.execute("select source, count(*) c from posts group by source"):
    w(f"  {r['source']}: {r['c']}")

w("keys with >=3 points:")
n = c.execute("select count(*) from (select product_key from price_points group by product_key having count(*)>=3)").fetchone()[0]
w(f"  {n}")

w("recent deals with sample>=3 and discount>=0.15:")
rows = list(c.execute("""
select id, product_name, seller, price, baseline_price, min_price, sample_count, discount_rate, grade, status
from deals
where sample_count>=3 and discount_rate>=0.15
order by discount_rate desc
limit 20
"""))
w(f"  count_top={len(rows)}")
for r in rows:
    disc = (r["discount_rate"] or 0) * 100
    w(f"  [{r['grade']}] {r['seller']} {r['product_name'][:50]} price={r['price']} base={r['baseline_price']} min={r['min_price']} n={r['sample_count']} disc={disc:.1f}%")

w("ppomppu parse rate:")
ok = 0
total = 0
for p in c.execute("select title from posts where source='ppomppu'"):
    total += 1
    if parse_title(p["title"]).price:
        ok += 1
w(f"  {ok}/{total} = {ok/total*100:.1f}%" if total else "  none")

out.write_text("\n".join(lines), encoding="utf-8")
print(out.read_text(encoding="utf-8"))
