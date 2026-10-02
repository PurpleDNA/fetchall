import pytest
from conftest import audio_only, media, video

from fetchall.config import Settings

URL = "https://video.example/watch/1"
MB = 1_000_000


def submit(harness, ip: str, url: str = URL):
    harness.extractor.script.setdefault(url, media())
    return harness.as_ip(ip).post("/jobs", json={"url": url})


def finish(harness, ip: str, url: str = URL) -> str:
    response = submit(harness, ip, url)
    assert response.status_code == 202, response.text
    harness.run_jobs()
    return response.json()["id"]


def test_defaults_match_the_spec():
    s = Settings()
    assert (s.max_concurrent_jobs, s.max_queued_jobs) == (2, 20)
    assert (s.jobs_per_ip_per_hour, s.max_height) == (10, 1080)
    assert (s.max_duration_seconds, s.max_filesize_bytes) == (3600, 1_000_000_000)


def test_the_queue_refuses_new_jobs_immediately_when_full(make_harness):
    harness = make_harness(max_queued_jobs=3)
    for n in range(3):
        assert submit(harness, f"10.0.0.{n}").status_code == 202

    response = submit(harness, "10.0.0.9")

    assert response.status_code == 503
    assert "busy" in response.json()["detail"].lower()


def test_queued_jobs_report_their_place_in_line(harness):
    ids = [submit(harness, f"10.0.0.{n}").json()["id"] for n in range(3)]

    assert harness.client.get(f"/jobs/{ids[2]}").json()["position"] == 3

    harness.run_jobs(max_jobs=1)

    assert harness.client.get(f"/jobs/{ids[2]}").json()["position"] == 2


def test_the_progress_stream_reports_the_place_in_line(make_harness):
    harness = make_harness(sse_max_seconds=0.3)
    submit(harness, "10.0.0.1")
    second = submit(harness, "10.0.0.2").json()["id"]

    events = harness.events(second)

    assert [(e["stage"], e.get("position")) for _, e in events] == [("queued", 2)]


def test_one_ip_gets_ten_jobs_an_hour_then_a_retry_after(harness):
    for _ in range(10):
        finish(harness, "203.0.113.5")
    harness.clock.advance(60)

    response = submit(harness, "203.0.113.5")

    assert response.status_code == 429
    retry_after = int(response.headers["retry-after"])
    assert 0 < retry_after <= 3600
    assert "try again" in response.json()["detail"].lower()
    assert submit(harness, "203.0.113.6").status_code == 202


def test_the_hourly_window_resets(harness):
    harness.clock.now = 1_700_000_000 - (1_700_000_000 % 3600)
    for _ in range(10):
        finish(harness, "203.0.113.5")

    harness.clock.advance(3599)
    assert submit(harness, "203.0.113.5").status_code == 429

    harness.clock.advance(1)
    assert submit(harness, "203.0.113.5").status_code == 202


def test_one_ip_can_only_have_one_job_in_progress(harness):
    assert submit(harness, "203.0.113.5").status_code == 202

    second = submit(harness, "203.0.113.5")

    assert second.status_code == 429
    assert "in progress" in second.json()["detail"]
    assert submit(harness, "203.0.113.6").status_code == 202

    harness.run_jobs()
    assert submit(harness, "203.0.113.5").status_code == 202


def test_a_failed_job_frees_the_ip_for_the_next_one(harness):
    from fetchall.extractor import ExtractionFailed, Outcome

    harness.extractor.script[URL] = ExtractionFailed(Outcome.NOT_FOUND, "Gone.")
    finish(harness, "203.0.113.5")

    assert submit(harness, "203.0.113.5", "https://video.example/watch/2").status_code == 202


def test_a_job_whose_worker_died_frees_the_ip(harness):
    from rq.job import Job, JobStatus

    job_id = submit(harness, "203.0.113.5").json()["id"]
    Job.fetch(job_id, connection=harness.rt.redis).set_status(JobStatus.FAILED)
    harness.client.get(f"/jobs/{job_id}")

    assert submit(harness, "203.0.113.5").status_code == 202


def test_preparing_counts_toward_the_same_limits(harness):
    mergeable = media(video(1080, audio=False), audio_only())
    harness.extractor.script[URL] = mergeable
    inspect_id = finish(harness, "203.0.113.5")
    client = harness.as_ip("203.0.113.5")

    assert client.post(f"/jobs/{inspect_id}/prepare/1080p").status_code == 202
    assert client.post(f"/jobs/{inspect_id}/prepare/1080p").status_code == 429


def test_videos_over_the_duration_cap_are_too_large(harness):
    harness.extractor.script[URL] = media(duration=61 * 60)

    job_id = finish(harness, "203.0.113.5")

    state = harness.client.get(f"/jobs/{job_id}").json()
    assert (state["stage"], state["outcome"]) == ("failed", "too_large")
    assert "60 minutes" in state["message"]


def test_qualities_above_the_caps_are_not_offered(harness):
    harness.extractor.script[URL] = media(
        video(2160, size=900 * MB),
        video(1080, size=1_200 * MB),
        video(720, size=400 * MB),
        audio_only(size=10 * MB),
    )

    job_id = finish(harness, "203.0.113.5")

    options = [o["id"] for o in harness.client.get(f"/jobs/{job_id}").json()["media"]["options"]]
    assert options == ["720p", "audio"]
    assert harness.client.get(f"/jobs/{job_id}/downloads/2160p").status_code == 404


@pytest.mark.parametrize("formats", [(video(2160),), (video(720, size=2_000 * MB),)])
def test_media_with_nothing_under_the_caps_is_too_large(harness, formats):
    harness.extractor.script[URL] = media(*formats)

    job_id = finish(harness, "203.0.113.5")

    assert harness.client.get(f"/jobs/{job_id}").json()["outcome"] == "too_large"


def test_caps_are_configurable(make_harness):
    harness = make_harness(max_height=480)
    harness.extractor.script[URL] = media(video(720), video(480))

    job_id = finish(harness, "203.0.113.5")

    options = [o["id"] for o in harness.client.get(f"/jobs/{job_id}").json()["media"]["options"]]
    assert options == ["480p"]


def test_ips_are_never_stored_in_the_clear(harness):
    finish(harness, "203.0.113.77")

    keys = b" ".join(harness.rt.redis.keys("*"))
    values = b" ".join(
        v
        for k in harness.rt.redis.keys("fetchall:*")
        if harness.rt.redis.type(k) == b"string"
        for v in [harness.rt.redis.get(k)]
    )
    assert b"203.0.113.77" not in keys + values


def test_the_worker_runs_as_many_processes_as_the_concurrency_cap(make_harness, monkeypatch):
    import fetchall.worker

    make_harness(max_concurrent_jobs=2)
    started = {}

    class FakePool:
        def __init__(self, queues, connection, num_workers):
            started["num_workers"] = num_workers

        def start(self):
            started["running"] = True

    monkeypatch.setattr(fetchall.worker, "WorkerPool", FakePool)
    fetchall.worker.main()

    assert started == {"num_workers": 2, "running": True}
