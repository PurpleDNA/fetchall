from pathlib import Path

import pytest
from conftest import audio_only, media, video
from pydantic import ValidationError
from rq.job import Job, JobStatus

from fetchall.config import Settings
from fetchall.extractor import ExtractionFailed, Outcome

URL = "https://video.example/watch/1"
IP = "203.0.113.42"
DAY = 24 * 3600


def run(harness, url: str = URL, ip: str = IP) -> str:
    job_id = harness.as_ip(ip).post("/jobs", json={"url": url}).json()["id"]
    harness.run_jobs()
    return job_id


def log(harness) -> list[dict]:
    return harness.rt.joblog.entries()


def test_a_finished_inspect_writes_one_entry(harness):
    harness.extractor.script[URL] = media()
    harness.clock.advance(1)
    job_id = run(harness)

    (entry,) = log(harness)

    assert entry == {
        "id": job_id,
        "visitor": harness.rt.limiter.visitor(IP),
        "kind": "inspect",
        "url": URL,
        "site": "Example",
        "tier": "server",
        "outcome": "ok",
        "bytes": 0,
        "created_at": 1_700_000_001.0,
        "finished_at": 1_700_000_001.0,
    }


def test_a_failed_job_records_its_outcome(harness):
    harness.extractor.script[URL] = ExtractionFailed(Outcome.LOGIN_REQUIRED, "Needs a login.")

    run(harness)

    assert [e["outcome"] for e in log(harness)] == ["login_required"]


def test_a_link_blocked_at_submission_is_logged(harness):
    harness.write_policy(f'blocked_urls = ["{URL}"]')

    run(harness)

    (entry,) = log(harness)
    assert (entry["outcome"], entry["visitor"]) == ("unsupported", harness.rt.limiter.visitor(IP))


def test_a_prepare_records_the_site_and_bytes(harness):
    harness.extractor.script[URL] = media(video(1080, audio=False), audio_only())
    harness.extractor.downloads[URL] = b"x" * 1234
    inspect_id = run(harness)

    harness.as_ip(IP).post(f"/jobs/{inspect_id}/prepare/1080p")
    harness.run_jobs()

    prepare = next(e for e in log(harness) if e["kind"] == "prepare")
    assert (prepare["site"], prepare["tier"], prepare["bytes"], prepare["outcome"]) == (
        "Example",
        "server",
        1234,
        "ok",
    )


def test_a_job_whose_worker_died_is_logged_as_internal(harness):
    job_id = harness.as_ip(IP).post("/jobs", json={"url": URL}).json()["id"]
    Job.fetch(job_id, connection=harness.rt.redis).set_status(JobStatus.FAILED)

    harness.client.get(f"/jobs/{job_id}")

    assert [e["outcome"] for e in log(harness)] == ["internal"]


def test_raw_ips_never_reach_the_log(harness):
    harness.extractor.script[URL] = media()
    run(harness)

    database = Path(harness.rt.settings.job_log_path)
    stored = b"".join(p.read_bytes() for p in database.parent.iterdir())
    assert IP.encode() not in stored


def test_entries_are_purged_after_seven_days(harness):
    harness.extractor.script[URL] = media()
    harness.extractor.script["https://video.example/watch/2"] = media()
    old = run(harness)

    harness.clock.advance(7 * DAY)
    run(harness, "https://video.example/watch/2", ip="203.0.113.43")
    assert {e["id"] for e in log(harness)} >= {old}

    harness.clock.advance(1)
    harness.rt.joblog.purge()
    assert old not in {e["id"] for e in log(harness)}
    assert len(log(harness)) == 1


def test_retention_is_configurable(make_harness):
    harness = make_harness(job_log_retention_seconds=DAY)
    harness.extractor.script[URL] = media()
    run(harness)

    harness.clock.advance(DAY + 1)
    harness.rt.joblog.purge()

    assert log(harness) == []


def test_production_refuses_to_start_without_a_secret_salt():
    with pytest.raises(ValidationError, match="FETCHALL_IP_HASH_SALT"):
        Settings(environment="production")

    assert Settings(environment="production", ip_hash_salt="s3cret").ip_hash_salt == "s3cret"
