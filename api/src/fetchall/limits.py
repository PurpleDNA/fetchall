import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from redis import Redis

from fetchall.config import Settings

WINDOW_SECONDS = 3600
BUSY_MESSAGE = "fetchall is busy right now. Try again in a minute or two."
IN_PROGRESS_MESSAGE = "You already have a job in progress. Wait for it to finish, then try again."


@dataclass(frozen=True)
class Caps:
    max_height: int
    max_duration_seconds: int
    max_filesize_bytes: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Caps":
        return cls(settings.max_height, settings.max_duration_seconds, settings.max_filesize_bytes)


class Refusal(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


class Limiter:
    def __init__(self, redis: Redis, settings: Settings, clock: Callable[[], float]):
        self._redis = redis
        self._settings = settings
        self._clock = clock

    def visitor(self, ip: str) -> str:
        digest = hashlib.sha256(f"{self._settings.ip_hash_salt}:{ip}".encode()).hexdigest()
        return digest[:24]

    def admit(self, visitor: str, job_id: str, queued: int) -> None:
        if queued >= self._settings.max_queued_jobs:
            raise Refusal(503, BUSY_MESSAGE)
        lock_ttl = self._settings.prepare_timeout_seconds + 60
        if not self._redis.set(_active_key(visitor), job_id, nx=True, ex=lock_ttl):
            raise Refusal(429, IN_PROGRESS_MESSAGE)
        now = self._clock()
        window = int(now // WINDOW_SECONDS)
        key = f"fetchall:rate:{visitor}:{window}"
        count = self._redis.incr(key)
        self._redis.expire(key, WINDOW_SECONDS + 60)
        if count > self._settings.jobs_per_ip_per_hour:
            self._redis.decr(key)
            self.release(visitor, job_id)
            retry_after = max(1, int((window + 1) * WINDOW_SECONDS - now))
            minutes = max(1, round(retry_after / 60))
            raise Refusal(
                429,
                f"You've reached the limit of {self._settings.jobs_per_ip_per_hour} downloads an "
                f"hour. Try again in about {minutes} minute{'s' if minutes != 1 else ''}.",
                retry_after,
            )

    def release(self, visitor: str, job_id: str) -> None:
        key = _active_key(visitor)
        if self._redis.get(key) == job_id.encode():
            self._redis.delete(key)


def _active_key(visitor: str) -> str:
    return f"fetchall:active:{visitor}"
