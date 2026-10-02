import logging
import time
from dataclasses import asdict

from rq.timeouts import JobTimeoutException

from fetchall import runtime
from fetchall.extractor import ExtractionFailed, MediaInfo, Outcome
from fetchall.jobs import DOWNLOADING, EXTRACTING, MERGING, READY, failed
from fetchall.quality import quality_options

log = logging.getLogger(__name__)

TIMEOUT_MESSAGE = "This took too long, so fetchall gave up. Try again in a moment."
CRASH_MESSAGE = "Something went wrong on our side. Try again in a moment."


def inspect(job_id: str, url: str) -> None:
    rt = runtime.current()
    rt.jobs.append(job_id, {"stage": EXTRACTING})
    try:
        media = rt.extractor.inspect(url)
    except ExtractionFailed as e:
        rt.jobs.append(job_id, failed(e.outcome, e.message))
        return
    except JobTimeoutException:
        rt.jobs.append(job_id, failed(Outcome.INTERNAL, TIMEOUT_MESSAGE))
        return
    except Exception:
        log.exception("inspect crashed for job %s", job_id)
        rt.jobs.append(job_id, failed(Outcome.INTERNAL, CRASH_MESSAGE))
        return
    rt.jobs.save_media(job_id, media)
    rt.jobs.append(job_id, {"stage": READY, "media": present(media)})


def prepare(
    job_id: str, url: str, format_ids: tuple[str, ...], container: str, filename: str
) -> None:
    rt = runtime.current()
    dest = rt.temp.reserve(job_id)
    report = _throttled(lambda event: rt.jobs.append(job_id, event))
    report({"stage": DOWNLOADING, "progress": 0.0}, force=True)

    def progress(stage: str, fraction: float | None) -> None:
        if stage == MERGING:
            report({"stage": MERGING}, force=True)
        else:
            report({"stage": DOWNLOADING, "progress": round(fraction or 0.0, 3)})

    try:
        path = rt.extractor.download(url, format_ids, container, dest, progress)
    except ExtractionFailed as e:
        rt.temp.discard(job_id)
        rt.jobs.append(job_id, failed(e.outcome, e.message))
        return
    except JobTimeoutException:
        rt.temp.discard(job_id)
        rt.jobs.append(job_id, failed(Outcome.INTERNAL, TIMEOUT_MESSAGE))
        return
    except Exception:
        log.exception("prepare crashed for job %s", job_id)
        rt.temp.discard(job_id)
        rt.jobs.append(job_id, failed(Outcome.INTERNAL, CRASH_MESSAGE))
        return
    prepared = rt.temp.complete(job_id, path, filename)
    rt.jobs.append(
        job_id,
        {
            "stage": READY,
            "file": {"url": f"/files/{job_id}", "filename": filename, "size": prepared.size},
        },
    )


def _throttled(emit, min_interval: float = 0.5):
    last = {"at": 0.0, "event": None}

    def report(event: dict, force: bool = False) -> None:
        now = time.monotonic()
        if force or (event != last["event"] and now - last["at"] >= min_interval):
            last.update(at=now, event=event)
            emit(event)

    return report


def present(media: MediaInfo) -> dict:
    return {
        "title": media.title,
        "url": media.url,
        "site": media.site,
        "uploader": media.uploader,
        "duration": media.duration,
        "thumbnail": media.thumbnail,
        "age_limit": media.age_limit,
        "options": [asdict(o) for o in quality_options(media)],
    }
