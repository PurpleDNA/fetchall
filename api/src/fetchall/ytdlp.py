from typing import Any
from urllib.parse import parse_qs, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from fetchall.egress.proxy import REFUSAL_PHRASE
from fetchall.extractor import ExtractionFailed, Format, MediaInfo, Outcome

BASE_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "skip_download": True,
    "noplaylist": True,
    "extract_flat": "in_playlist",
    "socket_timeout": 15,
}


class YtDlpExtractor:
    def __init__(self, proxy: str | None = None, options: dict[str, Any] | None = None):
        self._options = {**BASE_OPTIONS, **({"proxy": proxy} if proxy else {}), **(options or {})}

    def inspect(self, url: str) -> MediaInfo:
        with YoutubeDL(self._options) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except DownloadError as e:
                raise classify(str(e)) from e
        if not info:
            raise ExtractionFailed(Outcome.NO_MEDIA, "No video was found at that link.")
        return normalise(ydl.sanitize_info(info))


def normalise(info: dict[str, Any]) -> MediaInfo:
    if info.get("_type") in ("playlist", "multi_video"):
        raise ExtractionFailed(
            Outcome.UNSUPPORTED, "Playlists aren't supported. Paste a link to a single video."
        )

    site = info.get("extractor_key") or info.get("extractor") or "generic"
    raw_formats = info.get("formats") or ([info] if info.get("url") else [])
    usable = [f for f in raw_formats if _is_media(f)]
    formats = tuple(_format(f, site) for f in usable if not f.get("has_drm"))

    if not formats:
        if usable:
            raise ExtractionFailed(Outcome.DRM, "This video is DRM-protected.")
        raise ExtractionFailed(Outcome.NO_MEDIA, "No downloadable video was found at that link.")

    return MediaInfo(
        title=info.get("title") or "Untitled",
        url=info.get("webpage_url") or info.get("original_url") or "",
        site=site,
        uploader=info.get("uploader") or info.get("channel"),
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail"),
        age_limit=info.get("age_limit") or 0,
        formats=formats,
    )


def _is_media(f: dict[str, Any]) -> bool:
    if f.get("format_note") == "storyboard" or f.get("ext") == "mhtml":
        return False
    # yt-dlp uses "none" for a missing stream; None means unknown (assume present).
    return not (f.get("vcodec") == "none" and f.get("acodec") == "none")


def _format(f: dict[str, Any], site: str) -> Format:
    url = f.get("url") or ""
    protocol = f.get("protocol") or urlsplit(url).scheme
    return Format(
        id=str(f.get("format_id") or "0"),
        ext=f.get("ext") or "mp4",
        height=f.get("height"),
        has_video=f.get("vcodec") != "none",
        has_audio=f.get("acodec") != "none",
        filesize=f.get("filesize") or f.get("filesize_approx"),
        single_file=protocol in ("http", "https"),
        ip_bound=site.lower() == "youtube" or "ip" in parse_qs(urlsplit(url).query),
        url=url,
        headers=dict(f.get("http_headers") or {}),
    )


def classify(error: str) -> ExtractionFailed:
    if REFUSAL_PHRASE in error:
        return ExtractionFailed(Outcome.UNSUPPORTED, "That address isn't on the public internet.")
    if "Unsupported URL" in error:
        return ExtractionFailed(Outcome.NO_MEDIA, "No downloadable video was found at that link.")
    return ExtractionFailed(Outcome.INTERNAL, "Something went wrong fetching that link.")
