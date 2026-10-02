import json
import secrets
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from redis import Redis

from fetchall.extractor import Format, MediaInfo

Event = dict[str, Any]

QUEUED, EXTRACTING, READY, FAILED = "queued", "extracting", "ready", "failed"
DOWNLOADING, MERGING = "downloading", "merging"
TERMINAL = frozenset({READY, FAILED})


class JobStore:
    def __init__(
        self,
        redis: Redis,
        ttl_seconds: int,
        clock: Callable[[], float],
        on_finished: Callable[[str, str], None] = lambda owner, job_id: None,
    ):
        self._redis = redis
        self._ttl = ttl_seconds
        self._clock = clock
        self._on_finished = on_finished

    def create(self, kind: str, url: str, owner: str = "", job_id: str | None = None) -> str:
        job_id = job_id or new_job_id()
        self._redis.hset(_meta_key(job_id), mapping={"kind": kind, "url": url, "owner": owner})
        self._redis.expire(_meta_key(job_id), self._ttl)
        self.append(job_id, {"stage": QUEUED})
        return job_id

    def exists(self, job_id: str) -> bool:
        return bool(self._redis.exists(_meta_key(job_id)))

    def append(self, job_id: str, event: Event) -> None:
        event = {**event, "at": self._clock()}
        self._redis.rpush(_events_key(job_id), json.dumps(event))
        self._redis.expire(_events_key(job_id), self._ttl)
        if event["stage"] in TERMINAL:
            owner = self._redis.hget(_meta_key(job_id), "owner")
            if owner:
                self._on_finished(owner.decode(), job_id)

    def events(self, job_id: str, start: int = 0) -> list[Event]:
        return [json.loads(e) for e in self._redis.lrange(_events_key(job_id), start, -1)]

    def latest(self, job_id: str) -> Event | None:
        raw = self._redis.lindex(_events_key(job_id), -1)
        return json.loads(raw) if raw else None

    def save_media(self, job_id: str, media: MediaInfo) -> None:
        self._redis.hset(_meta_key(job_id), "media", json.dumps(asdict(media)))

    def load_media(self, job_id: str) -> MediaInfo | None:
        raw = self._redis.hget(_meta_key(job_id), "media")
        if not raw:
            return None
        data = json.loads(raw)
        data["formats"] = tuple(Format(**f) for f in data["formats"])
        return MediaInfo(**data)


def new_job_id() -> str:
    return secrets.token_urlsafe(12)


def failed(outcome: str, message: str) -> Event:
    return {"stage": FAILED, "outcome": outcome, "message": message}


def _meta_key(job_id: str) -> str:
    return f"fetchall:job:{job_id}"


def _events_key(job_id: str) -> str:
    return f"fetchall:job:{job_id}:events"
