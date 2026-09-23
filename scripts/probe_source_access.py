"""Read-only GitHub runner diagnostic. No proxies, database writes or schedules."""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Explicitly disable proxy configuration before importing the application.
for key in ('PPOMPPU_PROXY_URL', 'FMKOREA_PROXY_URL', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
            'http_proxy', 'https_proxy', 'all_proxy'):
    os.environ.pop(key, None)

from curl_cffi import requests
from playwright.async_api import async_playwright
from app.http_client import soft_block_reason
from app.sources import arca, damoang, quasarzone, fmkorea, coolenjoy
from app.sources.detail import parse_detail

SOURCES = [arca, damoang, quasarzone, fmkorea, coolenjoy]


def parse_posts(module, html):
    parser = getattr(module, 'parse_rss', None) or module.parse_list
    return parser(html)


def inspect(module, status, html):
    row = {'status': status, 'blocked': soft_block_reason(html), 'count': 0}
    posts = []
    if status == 200 and not row['blocked']:
        try:
            posts = parse_posts(module, html)
            row['count'] = len(posts)
            row['sample_urls'] = [p.url for p in posts[:2]]
            row['body_in_feed'] = sum(bool(p.body) for p in posts)
        except Exception as exc:
            row['parse_error'] = type(exc).__name__
    return row, posts


def detail_row(status, html, url):
    blocked = soft_block_reason(html)
    detail = parse_detail(html, url)
    return {'url': url, 'status': status, 'blocked': blocked,
            'body_chars': len(detail.body_html or ''), 'has_title': bool(detail.title),
            'success': status == 200 and not blocked and bool(detail.title and detail.body_html)}


def http_probe(module):
    with requests.Session(impersonate='chrome', trust_env=False) as session:
        response = session.get(module.LIST_URL, timeout=25)
        row, posts = inspect(module, response.status_code, response.text)
        row['details'] = []
        for post in posts[:2]:
            import time
            time.sleep(2)
            try:
                response = session.get(post.url, timeout=20)
                row['details'].append(detail_row(response.status_code, response.text, post.url))
            except Exception as exc:
                row['details'].append({'url': post.url, 'error': type(exc).__name__})
        return row


async def browser_probe(module, browser):
    context = await browser.new_context(locale='ko-KR', timezone_id='Asia/Seoul')
    try:
        page = await context.new_page()
        response = await page.goto(module.LIST_URL, wait_until='domcontentloaded', timeout=30000)
        # RSS must be read as XML, not Chromium's generated XML viewer DOM.
        rss = hasattr(module, 'RSS_URL')
        html = await response.text() if rss and response else await page.content()
        row, posts = inspect(module, response.status if response else None, html)
        if not posts and not rss:
            await page.wait_for_timeout(15000)
            html = await page.content()
            row, posts = inspect(module, response.status if response else None, html)
            # A JS navigation may clear the initial gate. Check the final DOM separately.
            if not row['blocked']:
                posts = parse_posts(module, html)
                row['count'] = len(posts)
                row['sample_urls'] = [p.url for p in posts[:2]]
        row['page_title'] = await page.title()
        row['details'] = []
        for post in posts[:2]:
            await asyncio.sleep(2)
            try:
                response = await page.goto(post.url, wait_until='domcontentloaded', timeout=25000)
                await page.wait_for_timeout(2000)
                row['details'].append(detail_row(response.status if response else None, await page.content(), post.url))
            except Exception as exc:
                row['details'].append({'url': post.url, 'error': type(exc).__name__})
        return row
    finally:
        await context.close()


async def main():
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'proxy': False, 'sources': {}}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for module in SOURCES:
            name = module.__name__.rsplit('.', 1)[-1]
            result = {}
            try:
                result['http'] = await asyncio.to_thread(http_probe, module)
            except Exception as exc:
                result['http'] = {'error': type(exc).__name__}
            try:
                result['browser'] = await browser_probe(module, browser)
            except Exception as exc:
                result['browser'] = {'error': type(exc).__name__}
            result['list_success'] = any(result[m].get('count', 0) > 0 for m in ('http', 'browser'))
            report['sources'][name] = result
            line = json.dumps({'source': name, **result}, ensure_ascii=True)
            print('::notice title=Source probe::' + line.replace('%', '%25'), flush=True)
            Path('source-access-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        await browser.close()
    summary = '| Source | HTTP count | Browser count | List success |\n|---|---:|---:|---|\n'
    for name, result in report['sources'].items():
        summary += f"| {name} | {result['http'].get('count', 0)} | {result['browser'].get('count', 0)} | {result['list_success']} |\n"
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(summary)


if __name__ == '__main__':
    asyncio.run(main())
