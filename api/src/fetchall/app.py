from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import urlsplit

import anyio
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, field_validator
from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus

from fetchall import tasks
from fetchall.extractor import Outcome
from fetchall.jobs import TERMINAL, Event, failed
from fetchall.runtime import Runtime, build

MAX_URL_LENGTH = 2048
WORKER_LOST_MESSAGE = "The job stopped unexpectedly. Try again in a moment."


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
    app = FastAPI(title="fetchall")
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
    def create_job(request: JobRequest):
        job_id = rt.jobs.create("inspect", request.url)
        rt.queue.enqueue(
            tasks.inspect,
            job_id,
            request.url,
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
        deadline = anyio.current_time() + rt.settings.job_ttl_seconds
        while anyio.current_time() < deadline:
            await anyio.to_thread.run_sync(current_state, job_id)
            events = await anyio.to_thread.run_sync(rt.jobs.events, job_id, cursor)
            for event in events:
                yield ServerSentEvent(data=event, id=str(cursor))
                cursor += 1
                if event["stage"] in TERMINAL:
                    return
            await anyio.sleep(rt.settings.sse_poll_seconds)

    def current_state(job_id: str) -> Event:
        # A worker killed mid-job never reports, so fall back to RQ's view of the job.
        state = rt.jobs.latest(job_id) or {}
        if state.get("stage") not in TERMINAL and _worker_gave_up(job_id):
            rt.jobs.append(job_id, failed(Outcome.INTERNAL, WORKER_LOST_MESSAGE))
            state = rt.jobs.latest(job_id)
        return state

    def _worker_gave_up(job_id: str) -> bool:
        try:
            status = Job.fetch(job_id, connection=rt.redis).get_status()
        except NoSuchJobError:
            return False
        return status in (JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED)

    return app
