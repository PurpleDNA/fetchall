from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class Outcome(StrEnum):
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
    single_file: bool
    # The media URL only works from the IP that extracted it (YouTube).
    ip_bound: bool
    url: str = ""
    vcodec: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


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


Progress = Callable[[str, float | None], None]


class Extractor(Protocol):
    def inspect(self, url: str) -> MediaInfo: ...

    def download(
        self, url: str, format_ids: tuple[str, ...], container: str, dest: Path, progress: Progress
    ) -> Path: ...
