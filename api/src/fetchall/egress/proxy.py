import asyncio
import base64
import binascii
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable
from ipaddress import IPv4Address, IPv6Address
from urllib.parse import unquote, urlsplit

from fetchall.egress.policy import PLAIN_HTTP_PORT, TUNNEL_PORT, is_public

log = logging.getLogger(__name__)

IP = IPv4Address | IPv6Address
Resolver = Callable[[str], Awaitable[set[IP]]]
Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter]
Connector = Callable[[IP, int], Awaitable[Streams]]
UpstreamConnector = Callable[[str, int], Awaitable[Streams]]

COUNT_EVERY_BYTES = 1_000_000
REFUSAL_PHRASE = "Blocked by fetchall egress policy"

HOP_BY_HOP = {b"proxy-connection", b"proxy-authorization", b"connection", b"keep-alive"}


class Refused(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


async def system_resolve(host: str) -> set[IP]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return {ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos}


async def open_tcp(ip: IP, port: int) -> Streams:
    return await asyncio.wait_for(asyncio.open_connection(str(ip), port), 10)


async def open_upstream(host: str, port: int) -> Streams:
    return await asyncio.wait_for(asyncio.open_connection(host, port), 10)


class EgressProxy:
    def __init__(
        self,
        resolve: Resolver = system_resolve,
        connect: Connector = open_tcp,
        max_bytes: int = 1_500_000_000,
        idle_timeout: float = 30,
        max_duration: float = 3600,
        upstream_for: Callable[[str], str | None] = lambda session: None,
        connect_upstream: UpstreamConnector = open_upstream,
        proxy_allowed: Callable[[], bool] = lambda: False,
        on_proxy_bytes: Callable[[int], None] = lambda count: None,
    ):
        self._resolve = resolve
        self._connect = connect
        self._upstream_for = upstream_for
        self._connect_upstream = connect_upstream
        self._proxy_allowed = proxy_allowed
        self._on_proxy_bytes = on_proxy_bytes
        self._max_bytes = max_bytes
        self._idle_timeout = idle_timeout
        self._max_duration = max_duration

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(self._max_duration):
                await self._serve(reader, writer)
        except Refused as e:
            log.info("egress refused: %s", e.reason)
            await _reply(writer, e.status, e.reason)
        except (TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            pass
        except asyncio.LimitOverrunError:
            await _reply(writer, 400, "Request header too large")
        except Exception:
            log.exception("egress failed")
            await _reply(writer, 502, "Egress error")
        finally:
            writer.close()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self._idle_timeout)
        request_line, _, headers = head.partition(b"\r\n")
        try:
            method, target, version = request_line.decode("latin-1").split(" ")
        except ValueError:
            raise Refused(400, "Malformed request line") from None

        upstream_proxy = self._upstream_proxy(_route(headers))
        count = self._on_proxy_bytes if upstream_proxy else None

        if method == "CONNECT":
            host, port = _split_host_port(target)
            if port != TUNNEL_PORT:
                raise Refused(403, f"Tunnels are only allowed to port {TUNNEL_PORT}")
            upstream = await self._open(host, port, upstream_proxy)
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
            await self._relay(reader, writer, upstream, count)
            return

        url = urlsplit(target)
        if url.scheme != "http" or not url.hostname:
            raise Refused(400, "Only absolute http:// URLs can be proxied")
        if (url.port or PLAIN_HTTP_PORT) != PLAIN_HTTP_PORT:
            raise Refused(403, f"Plain HTTP is only allowed to port {PLAIN_HTTP_PORT}")
        upstream = await self._open(url.hostname, PLAIN_HTTP_PORT, upstream_proxy)
        path = url.path or "/"
        if url.query:
            path += f"?{url.query}"
        upstream[1].write(f"{method} {path} {version}\r\n".encode() + _rewrite_headers(headers))
        await self._relay(reader, writer, upstream, count)

    def _upstream_proxy(self, route: str | None) -> str | None:
        if not route or not route.startswith("proxy-"):
            return None
        upstream = self._upstream_for(route.removeprefix("proxy-"))
        if not upstream:
            raise Refused(403, "The proxy tier isn't configured")
        if not self._proxy_allowed():
            raise Refused(403, "The proxy tier is over today's budget")
        return upstream

    async def _open(self, host: str, port: int, upstream_proxy: str | None = None) -> Streams:
        try:
            addresses = await self._resolve(host)
        except (OSError, ValueError):
            raise Refused(502, f"Could not resolve {host}") from None
        if not addresses:
            raise Refused(502, f"Could not resolve {host}")
        if not all(is_public(ip) for ip in addresses):
            raise Refused(403, f"{host} is not on the public internet")
        if upstream_proxy:
            return await self._tunnel(upstream_proxy, host, port)
        # Connect to the address we checked; never resolve again (defeats DNS rebinding).
        return await self._connect(min(addresses, key=str), port)

    async def _tunnel(self, upstream_proxy: str, host: str, port: int) -> Streams:
        proxy = urlsplit(upstream_proxy)
        reader, writer = await self._connect_upstream(proxy.hostname or "", proxy.port or 80)
        credentials = f"{unquote(proxy.username or '')}:{unquote(proxy.password or '')}"
        target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        writer.write(
            f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
            f"Proxy-Authorization: Basic {base64.b64encode(credentials.encode()).decode()}\r\n\r\n".encode()
        )
        await writer.drain()
        reply = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self._idle_timeout)
        if reply.split(b" ", 2)[1:2] != [b"200"]:
            writer.close()
            raise Refused(502, "The residential proxy refused the connection")
        return reader, writer

    async def _relay(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        upstream: Streams,
        count: Callable[[int], None] | None = None,
    ) -> None:
        up_reader, up_writer = upstream
        try:
            uploads = asyncio.create_task(self._copy(reader, up_writer, None, count))
            downloads = asyncio.create_task(self._copy(up_reader, writer, self._max_bytes, count))
            done, pending = await asyncio.wait(
                {uploads, downloads}, return_when=asyncio.FIRST_COMPLETED
            )
            if uploads in done and downloads not in done:
                done, pending = await asyncio.wait({downloads})
            for task in pending:
                task.cancel()
        finally:
            up_writer.close()

    async def _copy(
        self,
        source: asyncio.StreamReader,
        sink: asyncio.StreamWriter,
        limit: int | None,
        count: Callable[[int], None] | None = None,
    ) -> None:
        sent = uncounted = 0
        try:
            while chunk := await asyncio.wait_for(source.read(65536), self._idle_timeout):
                if limit is not None and sent + len(chunk) > limit:
                    chunk = chunk[: limit - sent]
                sent += len(chunk)
                uncounted += len(chunk)
                sink.write(chunk)
                await sink.drain()
                if count and uncounted >= COUNT_EVERY_BYTES:
                    count(uncounted)
                    uncounted = 0
                if limit is not None and sent >= limit:
                    return
        finally:
            if count and uncounted:
                count(uncounted)


def _route(headers: bytes) -> str | None:
    for line in headers.split(b"\r\n"):
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"proxy-authorization":
            scheme, _, token = value.strip().partition(b" ")
            if scheme.lower() != b"basic":
                return None
            try:
                return base64.b64decode(token).decode().partition(":")[0]
            except (binascii.Error, UnicodeDecodeError):
                return None
    return None


def _split_host_port(target: str) -> tuple[str, int]:
    host, _, port = target.rpartition(":")
    if not host or not port.isdigit():
        raise Refused(400, "CONNECT target must be host:port")
    return host.strip("[]"), int(port)


def _rewrite_headers(headers: bytes) -> bytes:
    kept = [
        line
        for line in headers.split(b"\r\n")
        if line and line.split(b":", 1)[0].strip().lower() not in HOP_BY_HOP
    ]
    return b"\r\n".join([*kept, b"Connection: close", b"", b""])


async def _reply(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
    body = f"{REFUSAL_PHRASE}: {reason}\n".encode()
    # yt-dlp surfaces only the status line, so the reason phrase carries the marker.
    phrase = {400: "Bad Request", 403: REFUSAL_PHRASE, 502: "Bad Gateway"}[status]
    try:
        writer.write(
            f"HTTP/1.1 {status} {phrase}\r\nContent-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    except ConnectionError:
        pass
