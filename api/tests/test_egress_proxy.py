import asyncio
import base64
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


class FakeResidentialProxy:
    def __init__(self):
        self.connects: list[tuple[str, str]] = []

    async def handle(self, reader, writer):
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        target = head.split(" ")[1]
        auth = next(
            (
                line.split(": ", 1)[1]
                for line in head.split("\r\n")
                if line.lower().startswith("proxy-authorization")
            ),
            "",
        )
        self.connects.append((target, base64.b64decode(auth.removeprefix("Basic ")).decode()))
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        request = await reader.readuntil(b"\r\n\r\n")
        body = b"via residential: " + request.split(b"\r\n")[0]
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()


def route_header(route: str) -> bytes:
    token = base64.b64encode(f"{route}:x".encode())
    return b"Proxy-Authorization: Basic " + token + b"\r\n"


@asynccontextmanager
async def chained_proxy(
    internet, residential, *, allowed=lambda: True, counted=None, upstream=True
):
    async with serve(residential.handle) as port:

        async def connect_upstream(host, upstream_port):
            assert (host, upstream_port) == ("gw.proxy.test", 823)
            return await asyncio.open_connection("127.0.0.1", port)

        template = "http://user-session-{session}:secret@gw.proxy.test:823"
        proxy = EgressProxy(
            resolve=internet.resolve,
            connect=internet.connect,
            upstream_for=(lambda session: template.format(session=session))
            if upstream
            else (lambda s: None),
            connect_upstream=connect_upstream,
            proxy_allowed=allowed,
            on_proxy_bytes=(counted.append if counted is not None else lambda n: None),
        )
        server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
        async with server:
            yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def test_proxy_routes_go_through_the_residential_proxy_with_a_sticky_session(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    residential = FakeResidentialProxy()
    async with chained_proxy(internet, residential) as proxy:
        first = await raw(
            proxy,
            b"GET http://public.test/a HTTP/1.1\r\nHost: public.test\r\n"
            + route_header("proxy-abc")
            + b"\r\n",
        )
        second = await raw(
            proxy,
            b"GET http://public.test/b HTTP/1.1\r\nHost: public.test\r\n"
            + route_header("proxy-abc")
            + b"\r\n",
        )
        other = await raw(
            proxy,
            b"GET http://public.test/c HTTP/1.1\r\nHost: public.test\r\n"
            + route_header("proxy-xyz")
            + b"\r\n",
        )

    assert first.endswith(b"via residential: GET /a HTTP/1.1")
    assert second.endswith(b"via residential: GET /b HTTP/1.1")
    assert other.endswith(b"via residential: GET /c HTTP/1.1")
    assert residential.connects == [
        ("public.test:80", "user-session-abc:secret"),
        ("public.test:80", "user-session-abc:secret"),
        ("public.test:80", "user-session-xyz:secret"),
    ]
    assert internet.connected_to == []


async def test_proxy_routes_tunnel_https_through_the_residential_proxy(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    residential = FakeResidentialProxy()
    async with chained_proxy(internet, residential) as proxy:
        reply = await raw(
            proxy,
            b"CONNECT public.test:443 HTTP/1.1\r\n" + route_header("proxy-abc") + b"\r\n"
            b"GET /secure HTTP/1.1\r\nHost: public.test\r\n\r\n",
        )

    assert reply.startswith(b"HTTP/1.1 200 Connection established")
    assert reply.endswith(b"via residential: GET /secure HTTP/1.1")
    assert residential.connects == [("public.test:443", "user-session-abc:secret")]


async def test_proxy_routes_are_still_ssrf_checked(internet):
    internet.dns["internal.test"] = [["10.0.0.5"]]
    residential = FakeResidentialProxy()
    async with chained_proxy(internet, residential) as proxy:
        reply = await raw(
            proxy, b"GET http://internal.test/ HTTP/1.1\r\n" + route_header("proxy-abc") + b"\r\n"
        )

    assert reply.startswith(b"HTTP/1.1 403")
    assert residential.connects == []


@pytest.mark.parametrize(
    ("allowed", "upstream"),
    [(lambda: False, True), (lambda: True, False)],
    ids=["over-budget", "not-configured"],
)
async def test_proxy_routes_are_refused_when_the_tier_is_unavailable(internet, allowed, upstream):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    residential = FakeResidentialProxy()
    async with chained_proxy(internet, residential, allowed=allowed, upstream=upstream) as proxy:
        reply = await raw(
            proxy, b"GET http://public.test/ HTTP/1.1\r\n" + route_header("proxy-abc") + b"\r\n"
        )

    assert reply.startswith(b"HTTP/1.1 403")
    assert residential.connects == []


async def test_proxied_bytes_are_counted(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    counted: list[int] = []
    async with chained_proxy(internet, FakeResidentialProxy(), counted=counted) as proxy:
        reply = await raw(
            proxy, b"GET http://public.test/a HTTP/1.1\r\n" + route_header("proxy-abc") + b"\r\n"
        )

    assert sum(counted) >= len(reply)


async def test_server_route_traffic_is_not_counted_or_proxied(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]
    counted: list[int] = []
    residential = FakeResidentialProxy()
    async with serve(http_handler(body=b"direct")) as port:
        internet.servers[(PUBLIC_IP, 80)] = port
        async with chained_proxy(internet, residential, counted=counted) as proxy:
            reply = await raw(
                proxy, b"GET http://public.test/ HTTP/1.1\r\nHost: public.test\r\n\r\n"
            )

    assert reply.endswith(b"direct")
    assert (residential.connects, counted) == ([], [])


async def test_an_unexpected_failure_is_answered_not_dropped(internet):
    internet.dns["public.test"] = [[PUBLIC_IP]]

    proxy = EgressProxy(
        resolve=internet.resolve,
        connect=internet.connect,
        upstream_for=lambda s: "http://u:p@gw:1",
        proxy_allowed=lambda: 1 / 0,
    )
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        reply = await raw(
            f"http://127.0.0.1:{port}",
            b"GET http://public.test/ HTTP/1.1\r\n" + route_header("proxy-a") + b"\r\n",
        )

    assert reply.startswith(b"HTTP/1.1 502")
