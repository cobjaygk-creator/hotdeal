import sqlite3
from collections import Counter
from pathlib import Path

c = sqlite3.connect("data/hotdeal.db")
keys = [r[0] for r in c.execute("select product_key from price_points")]
ctr = Counter(keys)
top = ctr.most_common(15)
lines = [f"{n}\t{k}" for k, n in top]
Path("data/top_keys.txt").write_text("\n".join(lines), encoding="utf-8")
print("unique", len(ctr), "posts", len(keys))
print("\n".join(lines))
