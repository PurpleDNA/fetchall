import argparse
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    visitor TEXT NOT NULL,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    site TEXT,
    tier TEXT,
    outcome TEXT NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    finished_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_finished_at ON jobs (finished_at);
"""

COLUMNS = (
    "id",
    "visitor",
    "kind",
    "url",
    "site",
    "tier",
    "outcome",
    "bytes",
    "created_at",
    "finished_at",
)


class JobLog:
    def __init__(self, path: Path, retention_seconds: int, clock: Callable[[], float]):
        self._path = path
        self._retention = retention_seconds
        self._clock = clock
        self._ready = False

    def record(self, entry: dict) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                f"INSERT OR REPLACE INTO jobs ({', '.join(COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in COLUMNS)})",
                [entry.get(c) for c in COLUMNS],
            )
            self._purge(db)

    def purge(self) -> None:
        with closing(self._connect()) as db, db:
            self._purge(db)

    def entries(self, url_contains: str = "", limit: int = 100) -> list[dict]:
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM jobs WHERE url LIKE ? ORDER BY finished_at DESC LIMIT ?",
                (f"%{url_contains}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def _purge(self, db: sqlite3.Connection) -> None:
        db.execute("DELETE FROM jobs WHERE finished_at < ?", (self._clock() - self._retention,))

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._path, timeout=5)
        if not self._ready:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            self._ready = True
        return db


def main() -> None:
    from fetchall.runtime import build

    parser = argparse.ArgumentParser(description="Search the fetchall job log.")
    parser.add_argument("url", nargs="?", default="", help="part of a URL to search for")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    for entry in build().joblog.entries(args.url, args.limit):
        print("\t".join(str(entry[c]) for c in COLUMNS))


if __name__ == "__main__":
    main()
