"""Probe Quasarzone from a GitHub runner; never writes production data."""
from __future__ import annotations
import argparse
import asyncio
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


async def browser_probe():
    from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout

    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "method": "chromium",
              "list": {}, "details": [], "success": False}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul")
        page = await context.new_page()

        async def read_page(url, selector):
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_selector(selector, state="attached", timeout=20000)
            except BrowserTimeout:
                pass
            html = await page.content()
            return html, {"status": response.status if response else None,
                          "blocked": soft_block_reason(html), "page_title": await page.title()}

        try:
            html, row = await read_page(LIST_URL, "div.v2-list-row--hotdeal")
            posts = parse_list(html) if not row["blocked"] else []
            row["count"] = len(posts)
            report["list"] = row
            await page.screenshot(path="quasarzone-browser-list.png", full_page=False)
            for post in posts[:3]:
                await asyncio.sleep(2)
                html, row = await read_page(post.url, ".view-content #new_contents, .view-content .note-editor")
                detail = parse_detail(html, post.url)
                row.update(url=post.url, title=detail.title,
                           body_chars=len(detail.body_html or ""),
                           image_count=(detail.body_html or "").count("<img "))
                report["details"].append(row)
            report["success"] = bool(posts) and any(
                not r["blocked"] and r.get("title") and r["body_chars"] > 0
                for r in report["details"]
            )
        except Exception as exc:
            report["error"] = type(exc).__name__
        finally:
            await browser.close()
    Path("quasarzone-browser-probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    if args.browser:
        asyncio.run(browser_probe())
    else:
        main()
