"""Wires the pieces together once per process, so API and worker share one definition."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from redis import Redis
from rq import Queue

from fetchall.config import Settings
from fetchall.extractor import Extractor
from fetchall.jobs import JobStore


@dataclass
class Runtime:
    settings: Settings
    redis: Redis
    queue: Queue
    jobs: JobStore
    extractor: Extractor


def build(
    settings: Settings | None = None,
    redis: Redis | None = None,
    extractor: Extractor | None = None,
    clock: Callable[[], float] = time.time,
) -> Runtime:
    settings = settings or Settings()
    if redis is None:
        redis = Redis.from_url(settings.redis_url, socket_timeout=5, socket_connect_timeout=2)
    if extractor is None:
        from fetchall.ytdlp import YtDlpExtractor

        extractor = YtDlpExtractor()
    return Runtime(
        settings=settings,
        redis=redis,
        queue=Queue(settings.queue_name, connection=redis),
        jobs=JobStore(redis, settings.job_ttl_seconds, clock),
        extractor=extractor,
    )


_current: Runtime | None = None


def current() -> Runtime:
    """The runtime for this process; jobs running in the worker look it up here."""
    global _current
    if _current is None:
        _current = build()
    return _current


def set_current(runtime: Runtime | None) -> None:
    global _current
    _current = runtime
