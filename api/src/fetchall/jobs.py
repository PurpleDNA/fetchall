"""Job state: an append-only list of progress events per job, kept in Redis.

The latest event is the job's current state. Event list indexes double as SSE event ids,
so a reconnecting client resumes exactly where it left off.
"""

import json
import secrets
from collections.abc import Callable
from typing import Any

from redis import Redis

Event = dict[str, Any]

QUEUED, EXTRACTING, READY, FAILED = "queued", "extracting", "ready", "failed"
TERMINAL = frozenset({READY, FAILED})


class JobStore:
    def __init__(self, redis: Redis, ttl_seconds: int, clock: Callable[[], float]):
        self._redis = redis
        self._ttl = ttl_seconds
        self._clock = clock

    def create(self, kind: str, url: str) -> str:
        job_id = secrets.token_urlsafe(12)
        self._redis.hset(_meta_key(job_id), mapping={"kind": kind, "url": url})
        self._redis.expire(_meta_key(job_id), self._ttl)
        self.append(job_id, {"stage": QUEUED})
        return job_id

    def exists(self, job_id: str) -> bool:
        return bool(self._redis.exists(_meta_key(job_id)))

    def append(self, job_id: str, event: Event) -> None:
        event = {**event, "at": self._clock()}
        self._redis.rpush(_events_key(job_id), json.dumps(event))
        self._redis.expire(_events_key(job_id), self._ttl)

    def events(self, job_id: str, start: int = 0) -> list[Event]:
        return [json.loads(e) for e in self._redis.lrange(_events_key(job_id), start, -1)]

    def latest(self, job_id: str) -> Event | None:
        raw = self._redis.lindex(_events_key(job_id), -1)
        return json.loads(raw) if raw else None


def failed(outcome: str, message: str) -> Event:
    return {"stage": FAILED, "outcome": outcome, "message": message}


def _meta_key(job_id: str) -> str:
    return f"fetchall:job:{job_id}"


def _events_key(job_id: str) -> str:
    return f"fetchall:job:{job_id}:events"
