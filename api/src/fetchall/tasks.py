import logging
import time
from dataclasses import asdict

from rq.timeouts import JobTimeoutException

from fetchall import runtime
from fetchall.extractor import ExtractionFailed, MediaInfo, Outcome
from fetchall.jobs import DOWNLOADING, EXTRACTING, MERGING, READY, failed
from fetchall.limits import Caps
from fetchall.policy import UNAVAILABLE_MESSAGE, on_domain
from fetchall.quality import quality_options
from fetchall.routes import SERVER, is_proxy, new_proxy_route
from fetchall.runtime import Runtime

log = logging.getLogger(__name__)

TIMEOUT_MESSAGE = "This took too long, so fetchall gave up. Try again in a moment."
CRASH_MESSAGE = "Something went wrong on our side. Try again in a moment."
LIMITED = "YouTube is limiting fetchall right now"


def inspect(job_id: str, url: str) -> None:
    rt = runtime.current()
    rt.jobs.append(job_id, {"stage": EXTRACTING})
    route = SERVER
    _use_route(rt, job_id, route)
    try:
        try:
            media = rt.extractor.inspect(url, SERVER)
        except ExtractionFailed as e:
            if not _may_fall_back(rt, job_id, url, e):
                raise
            route = _claim_proxy_route(rt, job_id)
            media = rt.extractor.inspect(url, route)
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

    rt.jobs.annotate(job_id, site=media.site)
    policy = rt.policy.current()
    if policy.blocks_media(media):
        rt.jobs.append(job_id, failed(Outcome.UNSUPPORTED, UNAVAILABLE_MESSAGE))
        return
    proxied = is_proxy(route)
    caps = rt.proxy_caps if proxied else rt.caps
    too_large = _over_caps(media, caps, proxied)
    if too_large:
        outcome = Outcome.BLOCKED if proxied else Outcome.TOO_LARGE
        rt.jobs.append(job_id, failed(outcome, too_large))
        return
    adult = policy.is_adult(media, url)
    rt.jobs.save_media(job_id, media, adult=adult, route=route)
    notice = _proxy_notice(caps) if proxied else None
    rt.jobs.append(job_id, {"stage": READY, "media": present(media, caps, adult, notice)})


def prepare(
    job_id: str,
    url: str,
    format_ids: tuple[str, ...],
    container: str,
    filename: str,
    site: str = "",
    route: str = SERVER,
    height: int | None = None,
) -> None:
    rt = runtime.current()
    rt.jobs.annotate(job_id, site=site)
    _use_route(rt, job_id, route)
    dest = rt.temp.reserve(job_id)
    report = _throttled(lambda event: rt.jobs.append(job_id, event))
    report({"stage": DOWNLOADING, "progress": 0.0}, force=True)

    def progress(stage: str, fraction: float | None) -> None:
        if stage == MERGING:
            report({"stage": MERGING}, force=True)
        else:
            report({"stage": DOWNLOADING, "progress": round(fraction or 0.0, 3)})

    def download(via: str):
        caps = rt.proxy_caps if is_proxy(via) else rt.caps
        return rt.extractor.download(
            url, format_ids, container, dest, progress, via, caps.max_filesize_bytes
        )

    try:
        try:
            path = download(route)
        except ExtractionFailed as e:
            if is_proxy(route) or not _may_fall_back(rt, job_id, url, e):
                raise
            if height and height > rt.proxy_caps.max_height:
                raise ExtractionFailed(
                    Outcome.BLOCKED, f"{LIMITED}. Try {rt.proxy_caps.max_height}p or lower."
                ) from e
            rt.temp.discard(job_id)
            dest = rt.temp.reserve(job_id)
            path = download(_claim_proxy_route(rt, job_id))
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
    rt.jobs.annotate(job_id, bytes=prepared.size)
    rt.jobs.append(
        job_id,
        {
            "stage": READY,
            "file": {"url": f"/files/{job_id}", "filename": filename, "size": prepared.size},
        },
    )


def _may_fall_back(rt: Runtime, job_id: str, url: str, failure: ExtractionFailed) -> bool:
    if failure.outcome != Outcome.BLOCKED:
        return False
    if not on_domain(url, tuple(rt.settings.proxy_domains)):
        return False
    return rt.proxy_budget.can_serve(rt.jobs.meta(job_id).get("owner", ""))


def _claim_proxy_route(rt: Runtime, job_id: str) -> str:
    rt.proxy_budget.claim(rt.jobs.meta(job_id).get("owner", ""))
    route = new_proxy_route()
    _use_route(rt, job_id, route)
    return route


def _use_route(rt: Runtime, job_id: str, route: str) -> None:
    rt.jobs.annotate(job_id, tier="proxy" if is_proxy(route) else "server", route=route)


def _throttled(emit, min_interval: float = 0.5):
    last = {"at": 0.0, "event": None}

    def report(event: dict, force: bool = False) -> None:
        now = time.monotonic()
        if force or (event != last["event"] and now - last["at"] >= min_interval):
            last.update(at=now, event=event)
            emit(event)

    return report


def _over_caps(media: MediaInfo, caps: Caps, proxied: bool) -> str | None:
    minutes = caps.max_duration_seconds // 60
    if media.duration and media.duration > caps.max_duration_seconds:
        if proxied:
            return f"{LIMITED}, so only videos up to {minutes} minutes can be fetched. Try later."
        return f"Videos longer than {minutes} minutes aren't supported."
    if not quality_options(media, caps):
        if proxied:
            return f"{LIMITED}, so this video is too large to fetch. Try again later."
        return "Every version of this video is over fetchall's size limits."
    return None


def _proxy_notice(caps: Caps) -> str:
    return (
        f"{LIMITED}, so downloads are capped at {caps.max_height}p and "
        f"{caps.max_duration_seconds // 60} minutes."
    )


def present(
    media: MediaInfo, caps: Caps | None = None, adult: bool = False, notice: str | None = None
) -> dict:
    return {
        "title": media.title,
        "url": media.url,
        "site": media.site,
        "uploader": media.uploader,
        "duration": media.duration,
        "thumbnail": media.thumbnail,
        "age_limit": media.age_limit,
        "age_restricted": adult,
        "notice": notice,
        "options": [asdict(o) for o in quality_options(media, caps)],
    }
