import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import fakeredis
import httpx2
import pytest
from fastapi.testclient import TestClient
from rq import SimpleWorker

from fetchall import runtime
from fetchall.app import create_app
from fetchall.config import Settings
from fetchall.extractor import Format, MediaInfo

FRONTEND = "http://localhost:5173"


class FakeExtractor:
    def __init__(self):
        self.script: dict[str, MediaInfo | Exception | Callable[[], MediaInfo]] = {}

    def inspect(self, url: str) -> MediaInfo:
        result = self.script.get(url)
        if result is None:
            raise AssertionError(f"FakeExtractor has no script for {url}")
        if isinstance(result, Exception):
            raise result
        return result() if callable(result) else result


class FakeUpstream:
    def __init__(self):
        self.files: dict[str, tuple[int, bytes, dict[str, str]]] = {}
        self.requests: list[httpx2.Request] = []

    def serve(self, url: str, body: bytes, status: int = 200, **headers: str) -> None:
        self.files[url] = (status, body, headers)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        status, body, headers = self.files.get(str(request.url), (404, b"", {}))
        range_header = request.headers.get("range")
        if status == 200 and range_header:
            start, end = (int(x) for x in range_header.removeprefix("bytes=").split("-"))
            part = body[start : end + 1]
            headers = {**headers, "content-range": f"bytes {start}-{end}/{len(body)}"}
            return httpx2.Response(206, content=part, headers=headers)
        return httpx2.Response(status, content=body, headers=headers)


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Harness:
    client: TestClient
    extractor: FakeExtractor
    clock: FakeClock
    server: fakeredis.FakeServer
    upstream: FakeUpstream
    rt: runtime.Runtime = field(repr=False)

    def run_jobs(self) -> None:
        """Run every queued job to completion in this process, like a worker would."""
        SimpleWorker([self.rt.queue], connection=self.rt.redis).work(burst=True)

    def inspect(self, url: str) -> str:
        response = self.client.post("/jobs", json={"url": url})
        assert response.status_code == 202, response.text
        return response.json()["id"]

    def inspected(self, url: str, media_info: MediaInfo) -> str:
        self.extractor.script[url] = media_info
        job_id = self.inspect(url)
        self.run_jobs()
        return job_id

    def events(self, job_id: str, last_event_id: str | None = None) -> list[tuple[str, dict]]:
        headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
        return parse_sse(self.client.get(f"/jobs/{job_id}/events", headers=headers).text)


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        if "data" in fields:
            events.append((fields.get("id"), json.loads(fields["data"])))
    return events


@pytest.fixture
def make_harness():
    def make(**settings) -> Harness:
        server = fakeredis.FakeServer()
        redis = fakeredis.FakeRedis(server=server)
        extractor, clock, upstream = FakeExtractor(), FakeClock(), FakeUpstream()
        rt = runtime.build(
            Settings(cors_origins=[FRONTEND], sse_poll_seconds=0.01, **settings),
            redis=redis,
            extractor=extractor,
            clock=clock,
            http_transport=httpx2.MockTransport(upstream.handle),
        )
        runtime.set_current(rt)
        return Harness(TestClient(create_app(rt)), extractor, clock, server, upstream, rt)

    yield make
    runtime.set_current(None)


@pytest.fixture
def harness(make_harness) -> Harness:
    return make_harness()


def video(
    height: int | None,
    *,
    audio: bool = True,
    size: int | None = None,
    single_file: bool = True,
    ip_bound: bool = False,
    headers: dict[str, str] | None = None,
) -> Format:
    format_id = f"v{height}{'a' if audio else ''}"
    return Format(
        id=format_id,
        ext="mp4",
        height=height,
        has_video=True,
        has_audio=audio,
        filesize=size,
        single_file=single_file,
        ip_bound=ip_bound,
        url=f"https://cdn.example/{format_id}.mp4",
        headers=headers or {"User-Agent": "yt-dlp-ua"},
    )


def audio_only(size: int | None = None, ext: str = "m4a", ip_bound: bool = False) -> Format:
    return Format(
        id=f"a-{ext}",
        ext=ext,
        height=None,
        has_video=False,
        has_audio=True,
        filesize=size,
        single_file=True,
        ip_bound=ip_bound,
        url=f"https://cdn.example/a.{ext}",
    )


def media(*formats: Format, **overrides) -> MediaInfo:
    defaults = MediaInfo(
        title="A short film",
        url="https://video.example/watch/1",
        site="Example",
        uploader="Someone",
        duration=125.0,
        thumbnail="https://video.example/thumb.jpg",
        age_limit=0,
        formats=formats or (video(720),),
    )
    return replace(defaults, **overrides)
