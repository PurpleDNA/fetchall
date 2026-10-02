"""The Extractor boundary: everything fetchall knows about a link comes through here.

The real implementation wraps yt-dlp (see `fetchall.ytdlp`); tests use a fake with the same shape.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Outcome(StrEnum):
    """Closed set of ways a job can fail. Only BLOCKED is eligible for proxy fallback."""

    BLOCKED = "blocked"
    LOGIN_REQUIRED = "login_required"
    NOT_FOUND = "not_found"
    NO_MEDIA = "no_media"
    DRM = "drm"
    TOO_LARGE = "too_large"
    UNSUPPORTED = "unsupported"
    INTERNAL = "internal"


class ExtractionFailed(Exception):
    def __init__(self, outcome: Outcome, message: str):
        super().__init__(message)
        self.outcome = outcome
        self.message = message


@dataclass(frozen=True)
class Format:
    id: str
    ext: str
    height: int | None
    has_video: bool
    has_audio: bool
    filesize: int | None
    # A single file fetchable over plain HTTP(S), as opposed to HLS/DASH segments.
    single_file: bool
    # The media URL only works from the IP that extracted it (e.g. YouTube).
    ip_bound: bool


@dataclass(frozen=True)
class MediaInfo:
    title: str
    url: str
    site: str
    uploader: str | None
    duration: float | None
    thumbnail: str | None
    age_limit: int
    formats: tuple[Format, ...]


class Extractor(Protocol):
    def inspect(self, url: str) -> MediaInfo:
        """Return media info for `url`, or raise ExtractionFailed."""
        ...
