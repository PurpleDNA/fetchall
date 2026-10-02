from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import urlsplit

import anyio
import httpx2
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, field_validator
from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from starlette.background import BackgroundTask

from fetchall import tasks
from fetchall.delivery import Delivery, UnknownOption, content_disposition, plan_delivery
from fetchall.extractor import Outcome
from fetchall.jobs import QUEUED, TERMINAL, Event, failed, new_job_id
from fetchall.limits import Refusal
from fetchall.policy import UNAVAILABLE_MESSAGE
from fetchall.runtime import Runtime, build

MAX_URL_LENGTH = 2048
WORKER_LOST_MESSAGE = "The job stopped unexpectedly. Try again in a moment."
AGE_CONFIRMATION_REQUIRED = "age_confirmation_required"
BUSY_MESSAGE = (
    "fetchall is busy preparing other downloads. Try again in a few minutes, "
    "or pick a quality that doesn't need processing."
)


class JobRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def must_be_a_web_link(cls, url: str) -> str:
        url = url.strip()
        parts = urlsplit(url)
        if len(url) > MAX_URL_LENGTH or parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("Enter a full web link starting with http:// or https://")
        return url


def create_app(rt: Runtime | None = None) -> FastAPI:
    rt = rt or build()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with anyio.create_task_group() as tg:
            tg.start_soon(sweep_forever)
            yield
            tg.cancel_scope.cancel()

    async def sweep_forever():
        while True:
            await anyio.to_thread.run_sync(rt.temp.sweep)
            await anyio.to_thread.run_sync(rt.joblog.purge)
            await anyio.sleep(rt.settings.sweep_interval_seconds)

    app = FastAPI(title="fetchall", lifespan=lifespan)

    @app.exception_handler(Refusal)
    def refused(_: Request, e: Refusal):
        headers = {"retry-after": str(e.retry_after)} if e.retry_after else None
        return JSONResponse({"detail": e.message}, status_code=e.status, headers=headers)

    def admit(request: Request, kind: str, url: str) -> str:
        visitor = rt.limiter.visitor(request.client.host if request.client else "unknown")
        job_id = new_job_id()
        rt.limiter.admit(visitor, job_id, queued=rt.queue.count)
        return rt.jobs.create(kind, url, owner=visitor, job_id=job_id)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=rt.settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        try:
            rt.redis.ping()
        except RedisError:
            return JSONResponse({"status": "degraded", "redis": "unreachable"}, status_code=503)
        return {"status": "ok", "redis": "ok"}

    @app.post("/jobs", status_code=202)
    def create_job(body: JobRequest, request: Request):
        if rt.policy.current().blocks_url(body.url):
            visitor = rt.limiter.visitor(request.client.host if request.client else "unknown")
            job_id = rt.jobs.create("inspect", body.url, owner=visitor)
            rt.jobs.append(job_id, failed(Outcome.UNSUPPORTED, UNAVAILABLE_MESSAGE))
            return {"id": job_id, **current_state(job_id)}
        job_id = admit(request, "inspect", body.url)
        rt.queue.enqueue(
            tasks.inspect,
            job_id,
            body.url,
            job_id=job_id,
            job_timeout=rt.settings.inspect_timeout_seconds,
            result_ttl=rt.settings.job_ttl_seconds,
            failure_ttl=rt.settings.job_ttl_seconds,
        )
        return {"id": job_id, **current_state(job_id)}

    def existing_job(job_id: str) -> str:
        if not rt.jobs.exists(job_id):
            raise HTTPException(404, "No such job (it may have expired).")
        return job_id

    Existing = Annotated[str, Depends(existing_job)]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: Existing):
        return {"id": job_id, **current_state(job_id)}

    @app.get("/jobs/{job_id}/events", response_class=EventSourceResponse)
    async def job_events(
        job_id: Existing, last_event_id: Annotated[str | None, Header()] = None
    ) -> AsyncIterator[ServerSentEvent]:
        cursor = int(last_event_id) + 1 if last_event_id and last_event_id.isdigit() else 0
        deadline = anyio.current_time() + rt.settings.sse_max_seconds
        last_position = None
        while anyio.current_time() < deadline:
            state = await anyio.to_thread.run_sync(current_state, job_id)
            events = await anyio.to_thread.run_sync(rt.jobs.events, job_id, cursor)
            for event in events:
                if event["stage"] == QUEUED and state.get("stage") == QUEUED:
                    event = {**event, "position": state.get("position")}
                    last_position = state.get("position")
                yield ServerSentEvent(data=event, id=str(cursor))
                cursor += 1
                if event["stage"] in TERMINAL:
                    return
            if not events and state.get("stage") == QUEUED and state["position"] != last_position:
                last_position = state["position"]
                yield ServerSentEvent(data=state)
            await anyio.sleep(rt.settings.sse_poll_seconds)

    def plan_for(job_id: str, option_id: str, age_confirmed: bool = False):
        media = rt.jobs.load_media(job_id)
        if media is None:
            raise HTTPException(409, "This link hasn't finished inspecting yet.")
        if rt.policy.current().blocks_media(media):
            raise HTTPException(404, UNAVAILABLE_MESSAGE)
        if rt.jobs.is_adult(job_id) and not age_confirmed:
            raise HTTPException(403, AGE_CONFIRMATION_REQUIRED)
        try:
            return plan_delivery(media, option_id, rt.caps)
        except UnknownOption:
            raise HTTPException(404, "That option isn't available for this video.") from None

    @app.get("/jobs/{job_id}/downloads/{option_id}")
    def download_plan(job_id: Existing, option_id: str, age_confirmed: bool = False):
        plan = plan_for(job_id, option_id, age_confirmed)
        body = {"delivery": plan.delivery, "filename": plan.filename}
        if plan.delivery == Delivery.DIRECT:
            body["url"] = plan.source_url
        elif plan.delivery == Delivery.STREAM:
            query = "?age_confirmed=true" if age_confirmed else ""
            body["url"] = f"/jobs/{job_id}/files/{option_id}{query}"
        return body

    @app.get("/jobs/{job_id}/files/{option_id}")
    async def stream_file(
        job_id: Existing,
        option_id: str,
        age_confirmed: bool = False,
        range: Annotated[str | None, Header()] = None,
    ):
        plan = await anyio.to_thread.run_sync(plan_for, job_id, option_id, age_confirmed)
        if plan.delivery != Delivery.STREAM:
            raise HTTPException(404, "This option isn't streamed by the server.")
        client = rt.http_client()
        headers = {**(plan.headers or {}), **({"Range": range} if range else {})}
        try:
            upstream = await client.send(
                client.build_request("GET", plan.source_url, headers=headers), stream=True
            )
        except httpx2.HTTPError:
            await client.aclose()
            raise HTTPException(502, "The site didn't send the file. Try again.") from None
        if upstream.status_code not in (200, 206):
            await upstream.aclose()
            await client.aclose()
            raise HTTPException(502, "The site didn't send the file. Try again.")

        async def body():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        passed_on = {
            k: upstream.headers[k]
            for k in ("content-type", "content-length", "content-range", "accept-ranges")
            if k in upstream.headers
        }
        if "content-encoding" in upstream.headers:
            passed_on.pop("content-length", None)
        return StreamingResponse(
            body(),
            status_code=upstream.status_code,
            headers={**passed_on, "content-disposition": content_disposition(plan.filename)},
        )

    @app.post("/jobs/{job_id}/prepare/{option_id}", status_code=202)
    def prepare(job_id: Existing, option_id: str, request: Request, age_confirmed: bool = False):
        plan = plan_for(job_id, option_id, age_confirmed)
        if plan.delivery != Delivery.PREPARE:
            raise HTTPException(409, "This option doesn't need preparing; download it directly.")
        rt.temp.sweep()
        if rt.temp.over_ceiling():
            raise HTTPException(503, BUSY_MESSAGE)
        media = rt.jobs.load_media(job_id)
        prepare_id = admit(request, "prepare", media.url)
        rt.queue.enqueue(
            tasks.prepare,
            prepare_id,
            media.url,
            plan.format_ids,
            plan.container,
            plan.filename,
            media.site,
            job_id=prepare_id,
            job_timeout=rt.settings.prepare_timeout_seconds,
            result_ttl=rt.settings.job_ttl_seconds,
            failure_ttl=rt.settings.job_ttl_seconds,
        )
        return {"id": prepare_id, **current_state(prepare_id)}

    @app.get("/files/{file_id}")
    def prepared_file(file_id: str, range: Annotated[str | None, Header()] = None):
        rt.temp.sweep()
        prepared = rt.temp.get(file_id)
        if prepared is None:
            raise HTTPException(404, "This file has expired. Fetch the link again.")
        done = (
            BackgroundTask(rt.temp.discard, file_id) if _reaches_end(range, prepared.size) else None
        )
        return FileResponse(
            prepared.path,
            headers={"content-disposition": content_disposition(prepared.filename)},
            background=done,
        )

    def current_state(job_id: str) -> Event:
        # A worker killed mid-job never reports, so fall back to RQ's view of the job.
        state = rt.jobs.latest(job_id) or {}
        if state.get("stage") not in TERMINAL and _worker_gave_up(job_id):
            rt.jobs.append(job_id, failed(Outcome.INTERNAL, WORKER_LOST_MESSAGE))
            state = rt.jobs.latest(job_id)
        if state.get("stage") == QUEUED:
            state = {**state, "position": _position(job_id)}
        return state

    def _position(job_id: str) -> int | None:
        try:
            index = Job.fetch(job_id, connection=rt.redis).get_position()
        except NoSuchJobError:
            return None
        return None if index is None else index + 1

    def _worker_gave_up(job_id: str) -> bool:
        try:
            status = Job.fetch(job_id, connection=rt.redis).get_status()
        except NoSuchJobError:
            return False
        return status in (JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED)

    return app


def _reaches_end(range_header: str | None, size: int) -> bool:
    # Only a response that serves the last byte completes the download; earlier ranges are resumes.
    if not range_header:
        return True
    spec = range_header.removeprefix("bytes=").strip()
    if "," in spec:
        return False
    start, _, end = spec.partition("-")
    if not start:
        return True
    return not end or int(end) >= size - 1
