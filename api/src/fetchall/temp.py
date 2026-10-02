import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from redis import Redis

PREPARING, READY = "preparing", "ready"


@dataclass(frozen=True)
class PreparedFile:
    path: Path
    filename: str
    size: int


class TempStore:
    def __init__(
        self,
        redis: Redis,
        root: Path,
        ttl_seconds: int,
        prepare_timeout_seconds: int,
        ceiling_bytes: int,
        clock: Callable[[], float],
    ):
        self._redis = redis
        self._root = root
        self._ttl = ttl_seconds
        self._prepare_timeout = prepare_timeout_seconds
        self._ceiling = ceiling_bytes
        self._clock = clock

    def usage(self) -> int:
        if not self._root.exists():
            return 0
        return sum(p.stat().st_size for p in self._root.rglob("*") if p.is_file())

    def over_ceiling(self) -> bool:
        return self.usage() >= self._ceiling

    def reserve(self, file_id: str) -> Path:
        dest = self._root / file_id
        dest.mkdir(parents=True, exist_ok=True)
        self._redis.hset(_key(file_id), mapping={"state": PREPARING, "since": self._clock()})
        self._redis.expire(_key(file_id), self._ttl + self._prepare_timeout + 3600)
        return dest

    def complete(self, file_id: str, path: Path, filename: str) -> PreparedFile:
        prepared = PreparedFile(path, filename, path.stat().st_size)
        self._redis.hset(
            _key(file_id),
            mapping={
                "state": READY,
                "since": self._clock(),
                "path": str(path),
                "filename": filename,
                "size": prepared.size,
            },
        )
        return prepared

    def get(self, file_id: str) -> PreparedFile | None:
        record = self._record(file_id)
        if record.get("state") != READY or self._expired(record):
            return None
        path = Path(record["path"])
        if not path.is_file():
            return None
        return PreparedFile(path, record["filename"], int(record["size"]))

    def discard(self, file_id: str) -> None:
        shutil.rmtree(self._root / file_id, ignore_errors=True)
        self._redis.delete(_key(file_id))

    def sweep(self) -> None:
        if not self._root.exists():
            return
        for entry in self._root.iterdir():
            record = self._record(entry.name)
            if not record or self._expired(record):
                self.discard(entry.name)

    def _record(self, file_id: str) -> dict[str, str]:
        raw = self._redis.hgetall(_key(file_id))
        return {k.decode(): v.decode() for k, v in raw.items()}

    def _expired(self, record: dict[str, str]) -> bool:
        limit = self._ttl if record.get("state") == READY else self._prepare_timeout + 60
        return self._clock() > float(record["since"]) + limit


def _key(file_id: str) -> str:
    return f"fetchall:file:{file_id}"
