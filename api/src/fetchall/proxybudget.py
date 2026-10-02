from collections.abc import Callable

from redis import Redis

from fetchall.config import Settings

DAY_SECONDS = 24 * 3600


class ProxyBudget:
    def __init__(self, redis: Redis, settings: Settings, clock: Callable[[], float]):
        self._redis = redis
        self._settings = settings
        self._clock = clock

    def upstream_for(self, session: str) -> str | None:
        template = self._settings.proxy_url
        return template.format(session=session) if template else None

    def bytes_today(self) -> int:
        return int(self._redis.get(self._key("bytes")) or 0)

    def add_bytes(self, count: int) -> None:
        key = self._key("bytes")
        self._redis.incrby(key, count)
        self._redis.expire(key, 2 * DAY_SECONDS)

    def allowed(self) -> bool:
        return (
            bool(self._settings.proxy_url) and self.bytes_today() < self._settings.proxy_daily_bytes
        )

    def can_serve(self, visitor: str) -> bool:
        used = int(self._redis.get(self._key(f"jobs:{visitor}")) or 0)
        return self.allowed() and used < self._settings.proxy_jobs_per_ip_per_day

    def claim(self, visitor: str) -> None:
        key = self._key(f"jobs:{visitor}")
        self._redis.incr(key)
        self._redis.expire(key, 2 * DAY_SECONDS)

    def _key(self, name: str) -> str:
        return f"fetchall:proxy:{name}:{int(self._clock() // DAY_SECONDS)}"
