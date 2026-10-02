"""Job functions executed by RQ workers, each in its own forked process."""

import logging
from dataclasses import asdict

from rq.timeouts import JobTimeoutException

from fetchall import runtime
from fetchall.extractor import ExtractionFailed, MediaInfo, Outcome
from fetchall.jobs import EXTRACTING, READY, failed
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
        # Raised inside the job by RQ when the hard timeout fires.
        rt.jobs.append(job_id, failed(Outcome.INTERNAL, TIMEOUT_MESSAGE))
        return
    except Exception:
        log.exception("inspect crashed for job %s", job_id)
        rt.jobs.append(job_id, failed(Outcome.INTERNAL, CRASH_MESSAGE))
        return
    rt.jobs.append(job_id, {"stage": READY, "media": present(media)})


def present(media: MediaInfo) -> dict:
    """What the visitor sees: the media summary plus quality choices, not raw formats."""
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
