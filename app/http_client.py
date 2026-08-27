from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass

import httpx

from app.config import (
    HTTP_TIMEOUT_SEC,
    MAX_RETRIES,
    MIN_REQUEST_INTERVAL_SEC,
    USER_AGENT,
)

log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    content: bytes
    not_modified: bool = False
    encoding: str | None = None


class PoliteClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            timeout=HTTP_TIMEOUT_SEC,
            follow_redirects=True,
        )
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._etag: dict[str, str] = {}
        self._modified: dict[str, str] = {}

    def _lock(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, encoding: str | None = None) -> FetchResult:
        host = httpx.URL(url).host or "default"
        extra: dict[str, str] = {}
        if url in self._etag:
            extra["If-None-Match"] = self._etag[url]
        if url in self._modified:
            extra["If-Modified-Since"] = self._modified[url]

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            async with self._lock(host):
                now = asyncio.get_event_loop().time()
                wait = MIN_REQUEST_INTERVAL_SEC - (now - self._last.get(host, 0.0))
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    resp = await self._client.get(url, headers=extra)
                except httpx.HTTPError as exc:
                    last_error = exc
                    await asyncio.sleep(2 ** attempt)
                    continue
                finally:
                    self._last[host] = asyncio.get_event_loop().time()

            if resp.status_code == 304:
                return FetchResult(url, 304, "", b"", not_modified=True)

            if resp.status_code == 403:
                log.warning("403 on %s, falling back to curl", url)
                return await self._curl_get(url, encoding)

            if resp.status_code in (429, 500, 502, 503, 504):
                delay = 2 ** attempt
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, int(retry_after))
                log.warning("retry %s status=%s wait=%s", url, resp.status_code, delay)
                await asyncio.sleep(delay)
                continue

            resp.raise_for_status()
            if etag := resp.headers.get("ETag"):
                self._etag[url] = etag
            if lm := resp.headers.get("Last-Modified"):
                self._modified[url] = lm
            return self._decode(url, resp.status_code, resp.content, encoding, resp.encoding)

        if last_error:
            raise last_error
        raise RuntimeError(f"retries exhausted for {url}")

    async def _curl_get(self, url: str, encoding: str | None) -> FetchResult:
        curl = "curl.exe" if sys.platform == "win32" else "curl"
        proc = await asyncio.create_subprocess_exec(
            curl,
            "-sL",
            "-A",
            USER_AGENT,
            "--max-time",
            str(int(HTTP_TIMEOUT_SEC)),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"curl failed {url}: {stderr.decode(errors='replace')}")
        return self._decode(url, 200, stdout, encoding, None)

    @staticmethod
    def _decode(
        url: str,
        status: int,
        raw: bytes,
        encoding: str | None,
        detected: str | None,
    ) -> FetchResult:
        used = encoding or detected or "utf-8"
        try:
            text = raw.decode(used, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
            used = "utf-8"
        return FetchResult(url, status, text, raw, encoding=used)
