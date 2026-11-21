"""Authenticated HTTP/HTTPS forward proxy for the home collector exit IP.

Runs natively on Windows so Railway's proxied requests no longer cross the
Windows -> WSL NAT hop, which was dropping connections intermittently.

Credentials ("user:password") come from HOME_PROXY_AUTH or the file
HOME_PROXY_AUTH_FILE (default: ~/.home_proxy_auth). Never commit them.
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import ipaddress
import logging
import os
import socket
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

LISTEN_HOST = os.environ.get("HOME_PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("HOME_PROXY_PORT", "28431"))
AUTH_FILE = Path(os.environ.get("HOME_PROXY_AUTH_FILE") or (Path.home() / ".home_proxy_auth"))
LOG_FILE = Path(os.environ.get("HOME_PROXY_LOG") or (Path.home() / "home_proxy.log"))
ALLOWED_PORTS = {80, 443, 8080, 8443}
CONNECT_TIMEOUT = 15
IDLE_TIMEOUT = 120
HEADER_LIMIT = 64 * 1024

log = logging.getLogger("home_proxy")


def _expected_auth() -> bytes:
    raw = (os.environ.get("HOME_PROXY_AUTH") or AUTH_FILE.read_text(encoding="utf-8")).strip()
    if ":" not in raw:
        raise SystemExit("proxy credentials must be 'user:password'")
    return b"Basic " + base64.b64encode(raw.encode("utf-8"))


EXPECTED_AUTH = b""


async def _resolve_public(host: str, port: int) -> str:
    """Resolve host and refuse anything that isn't a public address, so the
    proxy can't be used to reach the LAN (router admin, WSL, etc.)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for family, _, _, _, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_global:
            return sockaddr[0]
    raise PermissionError(f"non-public target {host}")


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


async def _reply(writer: asyncio.StreamWriter, status: str, extra: str = "") -> None:
    writer.write(f"HTTP/1.1 {status}\r\n{extra}Content-Length: 0\r\nConnection: close\r\n\r\n".encode())
    try:
        await writer.drain()
    finally:
        writer.close()


async def _handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
    peer = client_w.get_extra_info("peername")
    try:
        head = await asyncio.wait_for(client_r.readuntil(b"\r\n\r\n"), 30)
    except Exception:  # noqa: BLE001
        client_w.close()
        return
    lines = head.split(b"\r\n")
    try:
        method, target, version = lines[0].decode("latin-1").split(" ", 2)
    except ValueError:
        await _reply(client_w, "400 Bad Request")
        return
    headers: list[tuple[str, bytes]] = []
    auth = b""
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(b":")
        key = name.decode("latin-1").strip()
        if key.lower() == "proxy-authorization":
            auth = value.strip()
            continue
        if key.lower() == "proxy-connection":
            continue
        headers.append((key, value.strip()))

    if not hmac.compare_digest(auth, EXPECTED_AUTH):
        log.warning("auth rejected peer=%s target=%s", peer, target)
        await _reply(client_w, "407 Proxy Authentication Required", 'Proxy-Authenticate: Basic realm="proxy"\r\n')
        return

    if method.upper() == "CONNECT":
        host, _, port_s = target.rpartition(":")
        host = host.strip("[]")
        port = int(port_s) if port_s.isdigit() else 443
    else:
        parts = urlsplit(target)
        if parts.scheme != "http" or not parts.hostname:
            await _reply(client_w, "400 Bad Request")
            return
        host, port = parts.hostname, parts.port or 80

    if port not in ALLOWED_PORTS:
        await _reply(client_w, "403 Forbidden")
        return
    try:
        ip = await _resolve_public(host, port)
        up_r, up_w = await asyncio.wait_for(asyncio.open_connection(ip, port), CONNECT_TIMEOUT)
    except PermissionError:
        log.warning("blocked private target %s peer=%s", host, peer)
        await _reply(client_w, "403 Forbidden")
        return
    except Exception as exc:  # noqa: BLE001
        log.warning("upstream connect failed %s:%s %s", host, port, exc)
        await _reply(client_w, "502 Bad Gateway")
        return

    if method.upper() == "CONNECT":
        client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_w.drain()
    else:
        parts = urlsplit(target)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        out = [f"{method} {path} {version}".encode("latin-1")]
        out += [k.encode("latin-1") + b": " + v for k, v in headers if k.lower() != "connection"]
        out.append(b"Connection: close")
        up_w.write(b"\r\n".join(out) + b"\r\n\r\n")
        await up_w.drain()
    log.info("%s %s:%s peer=%s", method, host, port, peer[0] if peer else "?")
    await asyncio.gather(_pipe(client_r, up_w), _pipe(up_r, client_w))


async def main() -> None:
    global EXPECTED_AUTH
    EXPECTED_AUTH = _expected_auth()
    server = await asyncio.start_server(_handle, LISTEN_HOST, LISTEN_PORT, limit=HEADER_LIMIT)
    log.info("home proxy listening on %s:%s", LISTEN_HOST, LISTEN_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )
    asyncio.run(main())
