"""GitHub Actions용 FMKorea 수집 스크립트.

httpx로 fmkorea 목록 페이지를 가져와 서버 /api/ingest/fmkorea 로 전송.
"""
import os
import sys
import httpx

SERVER_URL = os.environ["SERVER_URL"].rstrip("/")
INGEST_SECRET = os.environ["INGEST_SECRET"]
FM_URL = "https://www.fmkorea.com/hotdeal"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.fmkorea.com/",
}


def fetch_html() -> str:
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        resp = client.get(FM_URL, headers=HEADERS)
        resp.raise_for_status()
        return resp.text


def push(html: str) -> dict:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{SERVER_URL}/api/ingest/fmkorea",
            json={"html": html},
            headers={"X-Ingest-Secret": INGEST_SECRET},
        )
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    print(f"Fetching {FM_URL} ...")
    try:
        html = fetch_html()
    except Exception as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetched {len(html):,} bytes. Pushing to server ...")
    try:
        result = push(html)
    except Exception as e:
        print(f"Push failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Done: {result}")
