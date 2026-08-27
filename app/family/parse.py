from __future__ import annotations

import json
import re
from datetime import date

from app.engine.dedupe import jaccard
from app.family import RawSale

OFFLINE_HINTS = ("오프라인", "세텍", "전시장", "팝업", "SETEC", "코엑스")
FAMILY_KEYWORDS = ("패밀리세일", "패밀리 세일", "팸세", "팸세일", "임직원", "시크릿 세일")
STOP_BRAND = {
    "세일",
    "시즌",
    "오프",
    "패밀리세일",
    "패밀리",
    "아카이브",
    "클리어런스",
    "플래시",
    "최대",
    "온라인",
    "스토어",
    "공식",
}

CAT_MAP = {
    "패션": "패션의류",
    "뷰티": "뷰티",
    "육아": "유아",
    "슈즈": "잡화",
    "잡화": "잡화",
    "식품": "식품",
}

DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})\s*~\s*(20\d{2}-\d{2}-\d{2})")
DISCOUNT_RE = re.compile(r"(?:~|최대\s*)?(\d{1,2})\s*%")


def is_family_title(title: str) -> bool:
    return any(k in title for k in FAMILY_KEYWORDS)


def parse_date_range(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    m = DATE_RE.search(text)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def parse_discount(title: str, hint: str | None = None) -> tuple[str | None, int | None]:
    blob = " ".join(x for x in (title, hint) if x)
    nums = [int(n) for n in DISCOUNT_RE.findall(blob)]
    if not nums:
        return None, None
    mx = max(nums)
    return f"~{mx}%", mx


def guess_sale_type(title: str, body: str | None = None) -> str:
    blob = f"{title} {body or ''}"
    if any(h in blob for h in OFFLINE_HINTS):
        return "오프라인"
    return "온라인"


def map_category(raw: str | None, title: str) -> tuple[list[str], str | None]:
    kind = None
    cats: list[str] = []
    text = (raw or "").strip()
    if "브랜드데이" in text or "브랜드데이" in title:
        kind = "브랜드데이"
    mapped = CAT_MAP.get(text)
    if mapped:
        cats.append(mapped)
    elif text and text not in ("브랜드데이",):
        cats.append("기타")
    if not cats:
        cats.append("기타")
    return cats, kind


def extract_brands(title: str, sale_kind: str | None) -> list[str]:
    cleaned = DISCOUNT_RE.sub("", title)
    cleaned = re.sub(r"[\[\]()~]", " ", cleaned)
    if "/" in cleaned or sale_kind == "브랜드데이":
        parts = [p.strip() for p in re.split(r"[/,]", cleaned) if p.strip()]
        brands = []
        for p in parts:
            token = re.split(r"\s+", p)[0]
            if token and token not in STOP_BRAND and not token.isdigit():
                brands.append(token)
        return brands[:8] or [title[:40]]
    head = re.split(r"\s+(시즌|패밀리|아카이브|클리어런스|플래시|임직원|시크릿)", cleaned, maxsplit=1)[0]
    token = head.strip().split(" ")[0]
    return [token] if token else [title[:40]]


def normalize_sale(raw: RawSale) -> dict:
    start, end = parse_date_range(raw.date_range or raw.title)
    label, mx = parse_discount(raw.title, raw.discount_hint)
    cats, kind = map_category(raw.category_raw, raw.title)
    brands = extract_brands(raw.title, kind)
    code = (raw.entry_code or "").strip() or None
    loc = (raw.location or "").strip() or None
    if not loc:
        loc = extract_location(raw.body or "")
    return {
        "source_name": raw.source_name,
        "source_post_id": raw.source_post_id,
        "title": raw.title,
        "brand_names": brands,
        "sale_type": guess_sale_type(raw.title, raw.body),
        "sale_kind": kind,
        "start_date": start,
        "end_date": end,
        "location": loc,
        "has_entry_code": bool(code),
        "entry_code": code,
        "categories": cats,
        "discount_label": label,
        "discount_max": mx,
        "source_url": raw.source_url,
        "deal_url": raw.deal_url,
    }


def extract_location(body: str) -> str | None:
    m = re.search(r"(세텍|SET EC|SETEC|코엑스|SET EC)[^\n]{0,40}", body, re.I)
    if m:
        return m.group(0).strip()
    return None


def extract_entry_code(text: str) -> str | None:
    m = re.search(r"입장\s*코드\s*[:：]?\s*([A-Za-z0-9_\-]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"할인\s*코드\s*[:：]?\s*([A-Za-z0-9_\-]+)", text)
    if m:
        return m.group(1)
    return None


def dates_overlap(a_start, a_end, b_start, b_end) -> bool:
    if not all([a_start, a_end, b_start, b_end]):
        return False
    return a_start <= b_end and b_start <= a_end


def brand_tokens(names: list[str] | str) -> set[str]:
    if isinstance(names, str):
        try:
            names = json.loads(names)
        except json.JSONDecodeError:
            names = [names]
    tokens: set[str] = set()
    for n in names or []:
        tokens.update(re.findall(r"[가-힣A-Za-z0-9]+", str(n).lower()))
    return tokens


def should_merge(a: dict, b: dict) -> bool:
    if not dates_overlap(a.get("start_date"), a.get("end_date"), b.get("start_date"), b.get("end_date")):
        return False
    ta, tb = brand_tokens(a.get("brand_names") or []), brand_tokens(b.get("brand_names") or [])
    if ta & tb:
        return True
    return jaccard(ta, tb) >= 0.5


def decode_sale_row(row: dict) -> dict:
    out = dict(row)
    for key in ("brand_names", "categories"):
        val = out.get(key)
        if isinstance(val, str):
            try:
                out[key] = json.loads(val)
            except json.JSONDecodeError:
                out[key] = [val] if val else []
    out["has_entry_code"] = bool(out.get("has_entry_code"))
    return out


def sale_status(start: str | None, end: str | None, today: date | None = None) -> str:
    today = today or date.today()
    if not start or not end:
        return "확인필요"
    try:
        s = date.fromisoformat(start[:10])
        e = date.fromisoformat(end[:10])
    except ValueError:
        return "확인필요"
    if today < s:
        return "예정"
    if today > e:
        return "종료"
    return "진행중"
