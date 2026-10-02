import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx2
from redis import Redis
from rq import Queue

from fetchall.config import Settings
from fetchall.extractor import Extractor
from fetchall.joblog import JobLog
from fetchall.jobs import READY, Event, JobStore
from fetchall.limits import Caps, Limiter
from fetchall.policy import PolicyFile
from fetchall.temp import TempStore


@dataclass
class Runtime:
    settings: Settings
    redis: Redis
    queue: Queue
    jobs: JobStore
    temp: TempStore
    limiter: Limiter
    caps: Caps
    policy: PolicyFile
    joblog: JobLog
    extractor: Extractor
    http_transport: httpx2.AsyncBaseTransport | None = None

    def http_client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            proxy=None if self.http_transport else self.settings.egress_proxy_url,
            transport=self.http_transport,
            timeout=httpx2.Timeout(30, read=self.settings.egress_idle_timeout_seconds),
            follow_redirects=True,
            trust_env=False,
        )


def build(
    settings: Settings | None = None,
    redis: Redis | None = None,
    extractor: Extractor | None = None,
    clock: Callable[[], float] = time.time,
    http_transport: httpx2.AsyncBaseTransport | None = None,
) -> Runtime:
    settings = settings or Settings()
    if redis is None:
        redis = Redis.from_url(settings.redis_url, socket_timeout=5, socket_connect_timeout=2)
    if extractor is None:
        from fetchall.ytdlp import YtDlpExtractor

        extractor = YtDlpExtractor(
            proxy=settings.egress_proxy_url,
            max_filesize=settings.max_filesize_bytes,
            pot_provider_url=settings.pot_provider_url,
            youtube_player_clients=settings.youtube_player_clients,
        )
    limiter = Limiter(redis, settings, clock)
    joblog = JobLog(Path(settings.job_log_path), settings.job_log_retention_seconds, clock)

    def finished(job_id: str, meta: dict[str, str], event: Event) -> None:
        if meta.get("owner"):
            limiter.release(meta["owner"], job_id)
        joblog.record(
            {
                "id": job_id,
                "visitor": meta.get("owner", ""),
                "kind": meta.get("kind", ""),
                "url": meta.get("url", ""),
                "site": meta.get("site"),
                "tier": meta.get("tier"),
                "outcome": "ok" if event["stage"] == READY else event.get("outcome", "internal"),
                "bytes": int(meta.get("bytes", 0)),
                "created_at": float(meta.get("created_at", clock())),
                "finished_at": clock(),
            }
        )

    return Runtime(
        settings=settings,
        redis=redis,
        queue=Queue(settings.queue_name, connection=redis),
        jobs=JobStore(redis, settings.job_ttl_seconds, clock, on_finished=finished),
        joblog=joblog,
        limiter=limiter,
        caps=Caps.from_settings(settings),
        policy=PolicyFile(Path(settings.policy_file)),
        temp=TempStore(
            redis,
            Path(settings.temp_dir),
            settings.temp_file_ttl_seconds,
            settings.prepare_timeout_seconds,
            settings.temp_ceiling_bytes,
            clock,
        ),
        extractor=extractor,
        http_transport=http_transport,
    )


_current: Runtime | None = None


def current() -> Runtime:
    global _current
    if _current is None:
        _current = build()
    return _current


def set_current(runtime: Runtime | None) -> None:
    global _current
    _current = runtime
