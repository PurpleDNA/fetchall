import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

from fetchall.extractor import Format, MediaInfo
from fetchall.limits import Caps
from fetchall.quality import quality_options

THUMBNAIL = "thumbnail"
HEADERS_THE_BROWSER_CANNOT_SEND = {"cookie", "referer", "authorization", "origin"}


class Delivery(StrEnum):
    DIRECT = "direct"
    STREAM = "stream"
    PREPARE = "prepare"


@dataclass(frozen=True)
class Plan:
    delivery: Delivery
    filename: str
    source_url: str = ""
    headers: dict[str, str] | None = None
    format_ids: tuple[str, ...] = ()
    container: str = ""


class UnknownOption(Exception):
    pass


def plan_delivery(media: MediaInfo, option_id: str, caps: Caps | None = None) -> Plan:
    if option_id == THUMBNAIL:
        if not media.thumbnail:
            raise UnknownOption(option_id)
        ext = PurePosixPath(urlsplit(media.thumbnail).path).suffix.lstrip(".") or "jpg"
        return Plan(Delivery.STREAM, filename_for(media.title, None, ext), media.thumbnail, {})

    option = next((o for o in quality_options(media, caps) if o.id == option_id), None)
    if option is None:
        raise UnknownOption(option_id)
    formats = {f.id: f for f in media.formats}
    chosen = [formats[i] for i in option.format_ids]
    first = chosen[0]
    label = None if option.audio_only else option.label

    if option.needs_merge or not first.single_file:
        container = "m4a" if option.audio_only else "mp4"
        filename = filename_for(media.title, label, container)
        return Plan(Delivery.PREPARE, filename, format_ids=option.format_ids, container=container)

    filename = filename_for(media.title, label, first.ext)
    if _browser_can_fetch(first):
        return Plan(Delivery.DIRECT, filename, first.url, first.headers)
    return Plan(Delivery.STREAM, filename, first.url, first.headers)


def _browser_can_fetch(f: Format) -> bool:
    return not f.ip_bound and not HEADERS_THE_BROWSER_CANNOT_SEND & {h.lower() for h in f.headers}


def filename_for(title: str, label: str | None, ext: str) -> str:
    name = unicodedata.normalize("NFC", title)
    name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")[:120].strip() or "video"
    if label:
        name = f"{name} ({label})"
    return f"{name}.{ext}"


def content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
