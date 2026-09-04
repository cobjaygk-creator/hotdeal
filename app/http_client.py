from __future__ import annotations

import asyncio
import logging
import shutil
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


def _soft_blocked(text: str) -> bool:
    head = (text or "")[:800].lower()
    return "403 forbidden" in head or "just a moment" in head


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
        self._proxy_clients: dict[str, httpx.AsyncClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._etag: dict[str, str] = {}
        self._modified: dict[str, str] = {}

    def _lock(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    def _client_for(self, proxy: str | None) -> httpx.AsyncClient:
        if not proxy:
            return self._client
        if proxy not in self._proxy_clients:
            self._proxy_clients[proxy] = httpx.AsyncClient(
                headers=BROWSER_HEADERS,
                timeout=HTTP_TIMEOUT_SEC,
                follow_redirects=True,
                proxy=proxy,
            )
        return self._proxy_clients[proxy]

    async def aclose(self) -> None:
        await self._client.aclose()
        for client in self._proxy_clients.values():
            await client.aclose()
        self._proxy_clients.clear()

    async def get(
        self,
        url: str,
        encoding: str | None = None,
        timeout: float | None = None,
        *,
        curl_fallback: bool = True,
        max_retries: int | None = None,
        proxy: str | None = None,
    ) -> FetchResult:
        host = httpx.URL(url).host or "default"
        req_timeout = timeout if timeout is not None else HTTP_TIMEOUT_SEC
        retries = MAX_RETRIES if max_retries is None else max(1, max_retries)
        http = self._client_for(proxy)
        extra: dict[str, str] = {}
        # Conditional GETs are only useful for the direct (non-proxy) client.
        if not proxy:
            if url in self._etag:
                extra["If-None-Match"] = self._etag[url]
            if url in self._modified:
                extra["If-Modified-Since"] = self._modified[url]

        last_error: Exception | None = None
        for attempt in range(retries):
            async with self._lock(host):
                now = asyncio.get_event_loop().time()
                wait = MIN_REQUEST_INTERVAL_SEC - (now - self._last.get(host, 0.0))
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    # Chrome TLS + residential proxy: httpx is challenged by
                    # Cloudflare even when the exit IP is Korean.
                    if proxy:
                        impersonated = await self._impersonate_get(
                            url, encoding, timeout=req_timeout, proxy=proxy
                        )
                        if impersonated is not None and not _soft_blocked(impersonated.text):
                            return impersonated
                    resp = await http.get(url, headers=extra, timeout=req_timeout)
                except httpx.HTTPError as exc:
                    last_error = exc
                    await asyncio.sleep(2 ** attempt)
                    continue
                finally:
                    self._last[host] = asyncio.get_event_loop().time()

            if resp.status_code == 304:
                return FetchResult(url, 304, "", b"", not_modified=True)

            if resp.status_code in (403, 430):
                if curl_fallback:
                    log.warning(
                        "%s on %s, falling back to curl (proxy=%s)",
                        resp.status_code,
                        url,
                        bool(proxy),
                    )
                    return await self._curl_get(
                        url, encoding, timeout=req_timeout, proxy=proxy
                    )
                log.warning(
                    "%s on %s (proxy=%s curl_fallback=%s)",
                    resp.status_code,
                    url,
                    bool(proxy),
                    curl_fallback,
                )
                return self._decode(
                    url, resp.status_code, resp.content, encoding, resp.encoding
                )

            if resp.status_code in (429, 500, 502, 503, 504):
                delay = 2 ** attempt
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, int(retry_after))
                log.warning("retry %s status=%s wait=%s", url, resp.status_code, delay)
                await asyncio.sleep(delay)
                continue

            resp.raise_for_status()
            final_url = str(resp.url) if resp.url else url
            decoded = self._decode(final_url, resp.status_code, resp.content, encoding, resp.encoding)
            # Some boards return HTTP 200 with an HTML 403 body to datacenter IPs.
            blocked = _soft_blocked(decoded.text)
            if blocked:
                self._etag.pop(url, None)
                self._modified.pop(url, None)
                if curl_fallback:
                    log.warning("soft-block body on %s, falling back to curl (proxy=%s)", url, bool(proxy))
                    return await self._curl_get(
                        url, encoding, timeout=req_timeout, proxy=proxy
                    )
                log.warning("soft-block body on %s (proxy=%s)", url, bool(proxy))
                return decoded
            if not proxy:
                if etag := resp.headers.get("ETag"):
                    self._etag[url] = etag
                if lm := resp.headers.get("Last-Modified"):
                    self._modified[url] = lm
            return decoded

        if last_error:
            raise last_error
        raise RuntimeError(f"retries exhausted for {url}")

    @staticmethod
    def _curl_argv(
        url: str,
        timeout: float | None = None,
        proxy: str | None = None,
    ) -> list[str]:
        curl = "curl.exe" if sys.platform == "win32" else "curl"
        max_time = str(int(timeout if timeout is not None else HTTP_TIMEOUT_SEC))
        referer = f"{httpx.URL(url).scheme}://{httpx.URL(url).host}/"
        argv = [
            curl,
            "-sL",
            "-A",
            USER_AGENT,
            "-e",
            referer,
            "-H",
            "Accept-Language: ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "--max-time",
            max_time,
        ]
        if proxy:
            argv.extend(["-x", proxy])
        argv.append(url)
        return argv

    async def _impersonate_get(
        self,
        url: str,
        encoding: str | None,
        timeout: float,
        proxy: str | None,
    ) -> FetchResult | None:
        try:
            from curl_cffi.requests import AsyncSession
        except ImportError:
            log.warning("curl_cffi not installed; skip Chrome TLS fetch")
            return None
        try:
            async with AsyncSession() as session:
                resp = await session.get(
                    url,
                    impersonate="chrome",
                    proxy=proxy,
                    timeout=timeout,
                    headers={"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"},
                    allow_redirects=True,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("chrome TLS fetch failed %s: %s", url, exc)
            return None
        return self._decode(url, int(resp.status_code), resp.content, encoding, None)

    async def _curl_get(
        self,
        url: str,
        encoding: str | None,
        timeout: float | None = None,
        proxy: str | None = None,
    ) -> FetchResult:
        curl = "curl.exe" if sys.platform == "win32" else "curl"
        if shutil.which(curl) is None:
            raise RuntimeError(
                f"403 from {url} and curl is not installed; "
                "install curl in the image for Cloudflare fallback"
            )
        proc = await asyncio.create_subprocess_exec(
            *self._curl_argv(url, timeout=timeout, proxy=proxy),
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

    async def post_json(self, url: str, payload: dict) -> None:
        resp = await self._client.post(url, json=payload, timeout=HTTP_TIMEOUT_SEC)
        if resp.status_code >= 400:
            raise RuntimeError(f"POST {url} -> {resp.status_code} {resp.text[:200]}")
