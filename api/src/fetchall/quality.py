from dataclasses import dataclass

from fetchall.extractor import Format, MediaInfo


@dataclass(frozen=True)
class QualityOption:
    id: str
    label: str
    height: int | None
    size: int | None
    needs_merge: bool
    audio_only: bool = False


def quality_options(media: MediaInfo) -> list[QualityOption]:
    audio = _best_audio(media.formats)
    by_height: dict[int, Format] = {}
    unsized: list[Format] = []
    for f in media.formats:
        if not f.has_video:
            continue
        if f.height is None:
            unsized.append(f)
        elif f.height not in by_height or _preference(f) > _preference(by_height[f.height]):
            by_height[f.height] = f

    options = [
        _video_option(f"{h}p", f"{h}p", by_height[h], audio)
        for h in sorted(by_height, reverse=True)
    ]
    if not options and unsized:
        options.append(_video_option("original", "Original", max(unsized, key=_preference), audio))
    if audio:
        options.append(
            QualityOption(
                id="audio",
                label="Audio only (M4A)",
                height=None,
                size=audio.filesize,
                needs_merge=False,
                audio_only=True,
            )
        )
    return options


def _video_option(id: str, label: str, f: Format, audio: Format | None) -> QualityOption:
    needs_merge = not f.has_audio and audio is not None
    size = f.filesize
    if needs_merge:
        size = f.filesize + audio.filesize if f.filesize and audio.filesize else None
    return QualityOption(id=id, label=label, height=f.height, size=size, needs_merge=needs_merge)


def _preference(f: Format) -> tuple:
    return (f.has_audio, f.single_file, f.filesize or 0)


def _best_audio(formats: tuple[Format, ...]) -> Format | None:
    audio_only = [f for f in formats if f.has_audio and not f.has_video]
    if not audio_only:
        return None
    return max(audio_only, key=lambda f: (f.ext == "m4a", f.filesize or 0))
