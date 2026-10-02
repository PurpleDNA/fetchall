import time

import pytest
from conftest import audio_only, media, video
from rq.job import Job, JobStatus

from fetchall.extractor import ExtractionFailed, Outcome

URL = "https://video.example/watch/1"
MB = 1_000_000


def test_creating_a_job_returns_an_id_immediately_while_queued(harness):
    response = harness.client.post("/jobs", json={"url": URL})

    assert response.status_code == 202
    body = response.json()
    assert body["id"]
    assert body["stage"] == "queued"
    assert harness.client.get(f"/jobs/{body['id']}").json()["stage"] == "queued"


def test_inspect_reports_media_info_and_quality_choices(harness):
    harness.extractor.script[URL] = media(
        video(1080, audio=False, size=40 * MB),
        video(720, size=25 * MB),
        video(720, audio=False, size=30 * MB),
        video(360, size=8 * MB, single_file=False),
        audio_only(size=3 * MB),
        audio_only(size=4 * MB, ext="webm"),
    )
    job_id = harness.inspect(URL)

    harness.run_jobs()

    state = harness.client.get(f"/jobs/{job_id}").json()
    assert state["stage"] == "ready"
    info = state["media"]
    assert info["title"] == "A short film"
    assert info["uploader"] == "Someone"
    assert info["duration"] == 125.0
    assert info["thumbnail"] == "https://video.example/thumb.jpg"
    choices = [(o["id"], o["size"], o["needs_merge"], o["audio_only"]) for o in info["options"]]
    assert choices == [
        ("1080p", 43 * MB, True, False),  # video-only: merged with the best (m4a) audio
        ("720p", 25 * MB, False, False),  # the version that already has sound wins
        ("360p", 8 * MB, False, False),
        ("audio", 3 * MB, False, True),
    ]


def test_size_is_unknown_when_any_merged_part_is_unknown(harness):
    harness.extractor.script[URL] = media(video(1080, audio=False, size=40 * MB), audio_only())
    job_id = harness.inspect(URL)

    harness.run_jobs()

    option = harness.client.get(f"/jobs/{job_id}").json()["media"]["options"][0]
    assert (option["id"], option["size"]) == ("1080p", None)


def test_media_without_known_heights_offers_the_original(harness):
    harness.extractor.script[URL] = media(video(None))
    job_id = harness.inspect(URL)

    harness.run_jobs()

    options = harness.client.get(f"/jobs/{job_id}").json()["media"]["options"]
    assert [o["id"] for o in options] == ["original"]


def test_progress_stream_replays_every_stage_in_order(harness):
    harness.extractor.script[URL] = media()
    job_id = harness.inspect(URL)
    harness.run_jobs()

    events = harness.events(job_id)

    assert [(id, e["stage"]) for id, e in events] == [
        ("0", "queued"),
        ("1", "extracting"),
        ("2", "ready"),
    ]
    assert events[-1][1]["media"]["title"] == "A short film"


def test_progress_stream_resumes_after_the_last_event_seen(harness):
    harness.extractor.script[URL] = media()
    job_id = harness.inspect(URL)
    harness.run_jobs()

    events = harness.events(job_id, last_event_id="1")

    assert [(id, e["stage"]) for id, e in events] == [("2", "ready")]


def test_polling_returns_the_same_state_as_the_last_streamed_event(harness):
    harness.extractor.script[URL] = media()
    job_id = harness.inspect(URL)
    harness.run_jobs()

    polled = harness.client.get(f"/jobs/{job_id}").json()

    assert polled == {"id": job_id, **harness.events(job_id)[-1][1]}


def test_events_are_stamped_with_the_clock(harness):
    harness.extractor.script[URL] = media()
    job_id = harness.inspect(URL)
    harness.clock.advance(5)
    harness.run_jobs()

    stamps = [e["at"] for _, e in harness.events(job_id)]

    assert stamps == [1_700_000_000.0, 1_700_000_005.0, 1_700_000_005.0]


def test_extraction_failure_is_reported_with_its_outcome(harness):
    harness.extractor.script[URL] = ExtractionFailed(Outcome.LOGIN_REQUIRED, "Needs a login.")
    job_id = harness.inspect(URL)

    harness.run_jobs()

    state = harness.client.get(f"/jobs/{job_id}").json()
    assert (state["stage"], state["outcome"], state["message"]) == (
        "failed",
        "login_required",
        "Needs a login.",
    )


def test_an_extractor_crash_is_reported_and_the_api_keeps_working(harness):
    harness.extractor.script[URL] = RuntimeError("boom")
    job_id = harness.inspect(URL)

    harness.run_jobs()

    state = harness.client.get(f"/jobs/{job_id}").json()
    assert (state["stage"], state["outcome"]) == ("failed", "internal")
    assert "boom" not in state["message"]
    assert harness.client.get("/health").status_code == 200


def test_a_job_past_its_hard_timeout_is_killed_and_reported(make_harness):
    harness = make_harness(inspect_timeout_seconds=1)

    def hang():
        time.sleep(10)
        return media()

    harness.extractor.script[URL] = hang
    job_id = harness.inspect(URL)

    started = time.monotonic()
    harness.run_jobs()

    assert time.monotonic() - started < 5
    state = harness.client.get(f"/jobs/{job_id}").json()
    assert (state["stage"], state["outcome"]) == ("failed", "internal")
    assert "too long" in state["message"]
    assert harness.client.get("/health").status_code == 200


def test_a_job_whose_worker_died_silently_is_reported_as_failed(harness):
    job_id = harness.inspect(URL)
    # Simulate the worker process being killed before it could report anything.
    Job.fetch(job_id, connection=harness.rt.redis).set_status(JobStatus.FAILED)

    state = harness.client.get(f"/jobs/{job_id}").json()

    assert (state["stage"], state["outcome"]) == ("failed", "internal")
    assert harness.events(job_id)[-1][1]["stage"] == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://video.example/file.mp4",
        "javascript:alert(1)",
        "not a link",
        "https://",
        "https://video.example/" + "a" * 2100,
    ],
)
def test_rejects_anything_but_a_web_link(harness, url):
    response = harness.client.post("/jobs", json={"url": url})

    assert response.status_code == 422


def test_unknown_jobs_are_not_found(harness):
    assert harness.client.get("/jobs/nope").status_code == 404
    assert harness.client.get("/jobs/nope/events").status_code == 404


def test_h264_is_preferred_over_vp9_at_the_same_height_so_the_mp4_plays_everywhere(harness):
    harness.extractor.script[URL] = media(
        video(1080, audio=False, size=60 * MB, vcodec="vp9"),
        video(1080, audio=False, size=50 * MB),
        audio_only(size=3 * MB),
    )
    job_id = harness.inspect(URL)
    harness.run_jobs()

    option = harness.client.get(f"/jobs/{job_id}").json()["media"]["options"][0]

    assert (option["id"], option["size"]) == ("1080p", 53 * MB)
