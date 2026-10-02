from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from fetchall.extractor import ExtractionFailed, Format, MediaInfo, Outcome, Progress
from fetchall.failures import MESSAGES, classify
from fetchall.routes import SERVER, egress_url

MERGE_STEPS = {"Merger", "FFmpegVideoRemuxer", "FFmpegFixupM3u8"}

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
    def __init__(
        self,
        proxy: str | None = None,
        max_filesize: int | None = None,
        pot_provider_url: str | None = None,
        youtube_player_clients: list[str] | None = None,
        options: dict[str, Any] | None = None,
    ):
        extractor_args: dict[str, dict[str, list[str]]] = {}
        if youtube_player_clients:
            extractor_args["youtube"] = {"player_client": youtube_player_clients}
        if pot_provider_url:
            extractor_args["youtubepot-bgutilhttp"] = {"base_url": [pot_provider_url]}
        self._egress = proxy
        self._options = {
            **BASE_OPTIONS,
            **({"proxy": proxy} if proxy else {}),
            **({"extractor_args": extractor_args} if extractor_args else {}),
            **(options or {}),
        }
        self._max_filesize = max_filesize

    def _routed(self, route: str) -> dict[str, Any]:
        if not self._egress:
            return self._options
        return {**self._options, "proxy": egress_url(self._egress, route)}

    def inspect(self, url: str, route: str = SERVER) -> MediaInfo:
        with YoutubeDL(self._routed(route)) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except DownloadError as e:
                raise classify(str(e)) from e
        if not info:
            raise ExtractionFailed(Outcome.NO_MEDIA, "No video was found at that link.")
        return normalise(ydl.sanitize_info(info))

    def download(
        self,
        url: str,
        format_ids: tuple[str, ...],
        container: str,
        dest: Path,
        progress: Progress,
        route: str = SERVER,
        max_filesize: int | None = None,
    ) -> Path:
        max_filesize = max_filesize or self._max_filesize
        fractions = dict.fromkeys(format_ids, 0.0)

        def on_progress(d: dict[str, Any]) -> None:
            format_id = str((d.get("info_dict") or {}).get("format_id", ""))
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if d["status"] == "finished":
                fractions[format_id] = 1.0
            elif d["status"] == "downloading" and total:
                fractions[format_id] = min(d.get("downloaded_bytes", 0) / total, 1.0)
            progress("downloading", sum(fractions.values()) / len(fractions))

        def on_postprocess(d: dict[str, Any]) -> None:
            if d["status"] == "started" and d.get("postprocessor") in MERGE_STEPS:
                progress("merging", None)

        options = {
            **self._routed(route),
            "skip_download": False,
            "max_filesize": max_filesize,
            "format": "+".join(format_ids),
            "paths": {"home": str(dest), "temp": str(dest)},
            "outtmpl": "media.%(ext)s",
            "merge_output_format": container,
            "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": container}],
            "progress_hooks": [on_progress],
            "postprocessor_hooks": [on_postprocess],
        }
        with YoutubeDL(options) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
            except DownloadError as e:
                raise classify(str(e)) from e
        downloads = (info or {}).get("requested_downloads") or []
        path = Path(downloads[0]["filepath"]) if downloads else None
        if path is None or not path.is_file():
            # yt-dlp skips, rather than fails, a file over max_filesize.
            if max_filesize:
                raise ExtractionFailed(Outcome.TOO_LARGE, MESSAGES[Outcome.TOO_LARGE])
            raise ExtractionFailed(Outcome.INTERNAL, "The download finished without a file.")
        return path


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
        uploader_id=info.get("uploader_id") or info.get("channel_id"),
        uploader_url=info.get("uploader_url") or info.get("channel_url"),
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
        vcodec=None if f.get("vcodec") in (None, "none") else f["vcodec"],
    )
