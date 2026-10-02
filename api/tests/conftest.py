import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import fakeredis
import pytest
from fastapi.testclient import TestClient
from rq import SimpleWorker

from fetchall import runtime
from fetchall.app import create_app
from fetchall.config import Settings
from fetchall.extractor import Format, MediaInfo

FRONTEND = "http://localhost:5173"


class FakeExtractor:
    """Scripted stand-in for yt-dlp: maps a URL to MediaInfo, an exception, or a callable."""

    def __init__(self):
        self.script: dict[str, MediaInfo | Exception | Callable[[], MediaInfo]] = {}

    def inspect(self, url: str) -> MediaInfo:
        result = self.script.get(url)
        if result is None:
            raise AssertionError(f"FakeExtractor has no script for {url}")
        if isinstance(result, Exception):
            raise result
        return result() if callable(result) else result


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
    rt: runtime.Runtime = field(repr=False)

    def run_jobs(self) -> None:
        """Run every queued job to completion in this process, like a worker would."""
        SimpleWorker([self.rt.queue], connection=self.rt.redis).work(burst=True)

    def inspect(self, url: str) -> str:
        response = self.client.post("/jobs", json={"url": url})
        assert response.status_code == 202, response.text
        return response.json()["id"]

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
        extractor, clock = FakeExtractor(), FakeClock()
        rt = runtime.build(
            Settings(cors_origins=[FRONTEND], sse_poll_seconds=0.01, **settings),
            redis=redis,
            extractor=extractor,
            clock=clock,
        )
        runtime.set_current(rt)
        return Harness(TestClient(create_app(rt)), extractor, clock, server, rt)

    yield make
    runtime.set_current(None)


@pytest.fixture
def harness(make_harness) -> Harness:
    return make_harness()


def video(
    height: int | None, *, audio: bool = True, size: int | None = None, single_file: bool = True
) -> Format:
    return Format(
        id=f"v{height}{'a' if audio else ''}",
        ext="mp4",
        height=height,
        has_video=True,
        has_audio=audio,
        filesize=size,
        single_file=single_file,
        ip_bound=False,
    )


def audio_only(size: int | None = None, ext: str = "m4a") -> Format:
    return Format(
        id=f"a-{ext}",
        ext=ext,
        height=None,
        has_video=False,
        has_audio=True,
        filesize=size,
        single_file=True,
        ip_bound=False,
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
