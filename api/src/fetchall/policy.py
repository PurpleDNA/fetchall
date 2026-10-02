import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fetchall.extractor import MediaInfo

log = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "This content is unavailable."


@dataclass(frozen=True)
class Policy:
    blocked_urls: frozenset[str] = frozenset()
    blocked_domains: tuple[str, ...] = ()
    blocked_uploaders: frozenset[str] = frozenset()
    adult_domains: tuple[str, ...] = ()

    @classmethod
    def from_toml(cls, data: dict) -> "Policy":
        return cls(
            blocked_urls=frozenset(_normal_url(u) for u in data.get("blocked_urls", [])),
            blocked_domains=tuple(d.lower().strip(".") for d in data.get("blocked_domains", [])),
            blocked_uploaders=frozenset(u.lower() for u in data.get("blocked_uploaders", [])),
            adult_domains=tuple(d.lower().strip(".") for d in data.get("adult_domains", [])),
        )

    def blocks_url(self, url: str) -> bool:
        return _normal_url(url) in self.blocked_urls or _on_domain(url, self.blocked_domains)

    def blocks_media(self, media: MediaInfo) -> bool:
        uploaders = {
            u.lower() for u in (media.uploader, media.uploader_id, media.uploader_url) if u
        }
        return self.blocks_url(media.url) or bool(uploaders & self.blocked_uploaders)

    def is_adult(self, media: MediaInfo, submitted_url: str = "") -> bool:
        return media.age_limit >= 18 or any(
            _on_domain(u, self.adult_domains) for u in (media.url, submitted_url) if u
        )


@dataclass
class PolicyFile:
    path: Path
    _policy: Policy = field(default_factory=Policy)
    _mtime: float | None = None

    def current(self) -> Policy:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._policy, self._mtime = Policy(), None
            return self._policy
        if mtime != self._mtime:
            try:
                self._policy = Policy.from_toml(tomllib.loads(self.path.read_text()))
            except (tomllib.TOMLDecodeError, OSError, TypeError, AttributeError):
                log.exception(
                    "ignoring invalid policy file %s; keeping the previous one", self.path
                )
            self._mtime = mtime
        return self._policy


def _normal_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _on_domain(url: str, domains: tuple[str, ...]) -> bool:
    host = (urlsplit(url.strip()).hostname or "").lower().strip(".")
    return any(host == d or host.endswith(f".{d}") for d in domains)
