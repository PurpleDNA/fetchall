import asyncio
import ipaddress
from contextlib import asynccontextmanager

import httpx2
import pytest

from fetchall.egress.proxy import EgressProxy

pytestmark = pytest.mark.anyio

PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "93.184.216.35"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeInternet:
    def __init__(self):
        self.dns: dict[str, list[list[str]]] = {}
        self.servers: dict[tuple[str, int], int] = {}
        self.connected_to: list[tuple[str, int]] = []

    async def resolve(self, host: str):
        answers = self.dns.get(host)
        if answers is None:
            return {ipaddress.ip_address(host)}
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        return {ipaddress.ip_address(a) for a in answer}

    async def connect(self, ip, port: int):
        self.connected_to.append((str(ip), port))
        local_port = self.servers[(str(ip), port)]
        return await asyncio.open_connection("127.0.0.1", local_port)


@asynccontextmanager
async def serve(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    async with server:
        yield server.sockets[0].getsockname()[1]


def http_handler(status: str = "200 OK", body: bytes = b"hello", headers: str = ""):
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n{headers}"
            "Connection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()

    return handle


@asynccontextmanager
async def running_proxy(internet: FakeInternet, **limits):
    proxy = EgressProxy(resolve=internet.resolve, connect=internet.connect, **limits)
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    async with server:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def raw(proxy_url: str, request: bytes, read_timeout: float = 5) -> bytes:
    host, port = proxy_url.removeprefix("http://").split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    writer.write(request)
    await writer.drain()
    data = b""
    try:
        while chunk := await asyncio.wait_for(reader.read(65536), read_timeout):
            data += chunk
    except (TimeoutError, ConnectionResetError):
        pass
    writer.close()
    return data


@pytest.fixture
def internet():
    return FakeInternet()


async def test_plain_http_to_a_public_host_is_relayed(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    async with serve(http_handler(body=b"video bytes")) as port:
        internet.servers[(PUBLIC_IP, 80)] = port
        async with running_proxy(internet) as proxy, httpx2.AsyncClient(proxy=proxy) as client:
            response = await client.get("http://public.test/clip.mp4")

    assert (response.status_code, response.content) == (200, b"video bytes")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1"])
async def test_hosts_resolving_to_non_public_addresses_are_refused(internet, address):
    internet.dns["internal.test"] = [[address]]
    async with running_proxy(internet) as proxy, httpx2.AsyncClient(proxy=proxy) as client:
        response = await client.get("http://internal.test/")

    assert response.status_code == 403
    assert internet.connected_to == []


async def test_a_host_with_any_non_public_answer_is_refused(internet):
    internet.dns["mixed.test"] = [[PUBLIC_IP, "10.0.0.5"]]
    async with running_proxy(internet) as proxy, httpx2.AsyncClient(proxy=proxy) as client:
        response = await client.get("http://mixed.test/")

    assert response.status_code == 403


async def test_a_redirect_into_a_private_range_is_refused(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    internet.dns["internal.test"] = [["10.0.0.5"]]
    redirect = http_handler("302 Found", b"", "Location: http://internal.test/admin\r\n")
    async with serve(redirect) as port:
        internet.servers[(PUBLIC_IP, 80)] = port
        async with (
            running_proxy(internet) as proxy,
            httpx2.AsyncClient(proxy=proxy, follow_redirects=True) as client,
        ):
            response = await client.get("http://public.test/")

    assert response.status_code == 403
    assert internet.connected_to == [(PUBLIC_IP, 80)]


async def test_connects_to_the_address_it_checked_even_if_dns_changes(internet):
    internet.dns["rebind.test"] = [[PUBLIC_IP], ["127.0.0.1"]]
    async with serve(http_handler()) as port:
        internet.servers[(PUBLIC_IP, 80)] = port
        async with running_proxy(internet) as proxy, httpx2.AsyncClient(proxy=proxy) as client:
            response = await client.get("http://rebind.test/")

    assert response.status_code == 200
    assert internet.connected_to == [(PUBLIC_IP, 80)]


async def test_https_tunnels_to_public_hosts_on_443(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]

    async def echo(reader, writer):
        writer.write(await reader.read(100))
        await writer.drain()
        writer.close()

    async with serve(echo) as port:
        internet.servers[(PUBLIC_IP, 443)] = port
        async with running_proxy(internet) as proxy:
            reply = await raw(proxy, b"CONNECT public.test:443 HTTP/1.1\r\n\r\nping")

    assert reply.startswith(b"HTTP/1.1 200")
    assert reply.endswith(b"ping")


@pytest.mark.parametrize(
    "request_line",
    [
        b"CONNECT internal.test:443 HTTP/1.1",
        b"CONNECT public.test:22 HTTP/1.1",
        b"CONNECT public.test:80 HTTP/1.1",
        b"GET http://public.test:8080/ HTTP/1.1",
        b"GET ftp://public.test/file HTTP/1.1",
        b"GET /relative HTTP/1.1",
    ],
)
async def test_only_http_on_80_and_tunnels_on_443_are_allowed(internet, request_line):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    internet.dns["internal.test"] = [["192.168.1.1"]]
    async with running_proxy(internet) as proxy:
        reply = await raw(proxy, request_line + b"\r\nHost: public.test\r\n\r\n")

    assert reply.split(b"\r\n")[0].split(b" ")[1] in (b"400", b"403")
    assert internet.connected_to == []


@pytest.mark.parametrize(
    "host",
    ["2130706433", "0x7f000001", "017700000001", "127.1", "[::ffff:127.0.0.1]", "[::1]"],
)
async def test_numeric_ip_spellings_are_resolved_before_checking(host):
    proxy = EgressProxy()
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        request = f"GET http://{host}/ HTTP/1.1\r\nHost: {host}\r\n\r\n".encode()
        reply = await raw(f"http://127.0.0.1:{port}", request)

    assert reply.startswith(b"HTTP/1.1 403")


async def test_responses_over_the_size_cap_are_cut_off(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    async with serve(http_handler(body=b"x" * 50_000)) as port:
        internet.servers[(PUBLIC_IP, 80)] = port
        async with running_proxy(internet, max_bytes=10_000) as proxy:
            reply = await raw(
                proxy, b"GET http://public.test/ HTTP/1.1\r\nHost: public.test\r\n\r\n"
            )

    assert len(reply) <= 10_000


async def test_stalled_transfers_are_closed(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]

    async def stall(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\npartial")
        await writer.drain()
        await reader.read()
        writer.close()

    async with serve(stall) as port:
        internet.servers[(PUBLIC_IP, 80)] = port
        async with running_proxy(internet, idle_timeout=0.3) as proxy:
            loop = asyncio.get_running_loop()
            started = loop.time()
            reply = await raw(
                proxy, b"GET http://public.test/ HTTP/1.1\r\nHost: public.test\r\n\r\n"
            )

    assert reply.endswith(b"partial")
    assert loop.time() - started < 3
