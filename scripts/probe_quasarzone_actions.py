"""Probe Quasarzone from a GitHub runner; never writes production data."""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from curl_cffi import requests
from app.http_client import soft_block_reason
from app.sources.quasarzone import LIST_URL, parse_list
from app.sources.detail import parse_detail


def main():
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "list": {}, "details": []}
    session = requests.Session(impersonate="chrome")
    posts = []
    try:
        response = session.get(LIST_URL, timeout=25)
        block = soft_block_reason(response.text)
        if response.status_code == 200 and not block:
            posts = parse_list(response.text)
        report["list"] = {"status": response.status_code, "blocked": block, "count": len(posts)}
        urls = [p.url for p in posts[:3]]
        urls += ["https://quasarzone.com/bbs/qb_saleinfo/views/1986876",
                 "https://quasarzone.com/bbs/qb_saleinfo/views/1986902"]
        for url in dict.fromkeys(urls):
            time.sleep(2)
            row = {"url": url}
            try:
                response = session.get(url, timeout=25)
                parsed = parse_detail(response.text, url)
                row.update(status=response.status_code, blocked=soft_block_reason(response.text),
                           title=parsed.title, body_chars=len(parsed.body_html or ""),
                           image_count=(parsed.body_html or "").count("<img "),
                           missing_page="존재하지 않는 페이지" in response.text)
            except Exception as exc:
                row["error"] = type(exc).__name__
            report["details"].append(row)
    except Exception as exc:
        report["list"]["error"] = type(exc).__name__
    finally:
        session.close()
    report["success"] = bool(posts) and any(
        r.get("status") == 200 and not r.get("blocked") and r.get("title") and r.get("body_chars", 0) > 0
        for r in report["details"] if r["url"] in {p.url for p in posts[:3]}
    )
    Path("quasarzone-probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
