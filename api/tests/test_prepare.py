import time
from pathlib import Path

import pytest
from conftest import audio_only, media, video

from fetchall.extractor import ExtractionFailed, Outcome

URL = "https://video.example/watch/1"
MERGEABLE = media(video(1080, audio=False), audio_only(), video(360, ip_bound=True))


def prepared(harness, *, data: bytes = b"merged-bytes", option: str = "1080p") -> dict:
    harness.extractor.downloads[URL] = data
    inspect_id = harness.inspected(URL, MERGEABLE)
    response = harness.client.post(f"/jobs/{inspect_id}/prepare/{option}")
    assert response.status_code == 202, response.text
    harness.run_jobs()
    return {"inspect_id": inspect_id, "id": response.json()["id"]}


def temp_files(harness) -> list[Path]:
    root = Path(harness.rt.settings.temp_dir)
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def test_preparing_reports_downloading_merging_and_the_ready_file(harness):
    job = prepared(harness)

    events = [e for _, e in harness.events(job["id"])]

    stages = [e["stage"] for e in events]
    assert stages[0] == "queued"
    assert stages[-2:] == ["merging", "ready"]
    progress = [e["progress"] for e in events if e["stage"] == "downloading"]
    assert progress[0] == 0.0
    assert progress == sorted(progress)
    assert events[-1]["file"] == {
        "url": f"/files/{job['id']}",
        "filename": "A short film (1080p).mp4",
        "size": len(b"merged-bytes"),
    }
    assert harness.extractor.download_calls == [(URL, ("v1080", "a-m4a"), "mp4")]


def test_the_prepared_file_is_served_with_its_size_and_deleted_after_download(harness):
    job = prepared(harness)

    file = harness.client.get(f"/files/{job['id']}")

    assert file.status_code == 200
    assert file.content == b"merged-bytes"
    assert file.headers["content-length"] == "12"
    assert file.headers["content-disposition"].startswith(
        'attachment; filename="A short film (1080p).mp4"'
    )
    assert temp_files(harness) == []
    assert harness.client.get(f"/files/{job['id']}").status_code == 404


def test_a_partial_range_keeps_the_file_so_the_download_can_resume(harness):
    job = prepared(harness, data=b"0123456789")

    first = harness.client.get(f"/files/{job['id']}", headers={"Range": "bytes=0-3"})
    assert (first.status_code, first.content) == (206, b"0123")
    assert len(temp_files(harness)) == 1

    rest = harness.client.get(f"/files/{job['id']}", headers={"Range": "bytes=4-"})
    assert (rest.status_code, rest.content) == (206, b"456789")
    assert rest.headers["content-range"] == "bytes 4-9/10"
    assert temp_files(harness) == []


def test_an_uncollected_file_expires_after_its_time_to_live(harness):
    job = prepared(harness)

    harness.clock.advance(15 * 60 + 1)

    assert harness.client.get(f"/files/{job['id']}").status_code == 404
    assert temp_files(harness) == []


def test_a_file_is_still_available_just_before_it_expires(harness):
    job = prepared(harness)

    harness.clock.advance(15 * 60 - 1)

    assert harness.client.get(f"/files/{job['id']}").status_code == 200


def test_expired_files_are_swept_even_if_nobody_asks_for_them(harness):
    first = prepared(harness)
    harness.clock.advance(15 * 60 + 1)

    harness.client.post(f"/jobs/{first['inspect_id']}/prepare/1080p")

    assert not (Path(harness.rt.settings.temp_dir) / first["id"]).exists()


def test_new_merges_are_refused_over_the_disk_ceiling_but_other_downloads_work(make_harness):
    harness = make_harness(temp_ceiling_bytes=10)
    job = prepared(harness, data=b"x" * 20)

    refused = harness.client.post(f"/jobs/{job['inspect_id']}/prepare/1080p")
    streamed = harness.client.get(f"/jobs/{job['inspect_id']}/downloads/360p")

    assert refused.status_code == 503
    assert "busy" in refused.json()["detail"]
    assert streamed.json()["delivery"] == "stream"


def test_merges_resume_once_space_is_freed(make_harness):
    harness = make_harness(temp_ceiling_bytes=10)
    job = prepared(harness, data=b"x" * 20)
    harness.client.get(f"/files/{job['id']}")

    assert harness.client.post(f"/jobs/{job['inspect_id']}/prepare/1080p").status_code == 202


def test_a_failed_download_is_reported_and_leaves_nothing_behind(harness):
    harness.extractor.downloads[URL] = ExtractionFailed(Outcome.BLOCKED, "The site is blocking us.")
    inspect_id = harness.inspected(URL, MERGEABLE)
    prepare_id = harness.client.post(f"/jobs/{inspect_id}/prepare/1080p").json()["id"]

    harness.run_jobs()

    state = harness.client.get(f"/jobs/{prepare_id}").json()
    assert (state["stage"], state["outcome"]) == ("failed", "blocked")
    assert temp_files(harness) == []


def test_a_prepare_past_its_hard_timeout_is_killed_and_cleaned_up(make_harness):
    harness = make_harness(prepare_timeout_seconds=1)

    def hang() -> bytes:
        time.sleep(10)
        return b""

    harness.extractor.downloads[URL] = hang
    inspect_id = harness.inspected(URL, MERGEABLE)
    prepare_id = harness.client.post(f"/jobs/{inspect_id}/prepare/1080p").json()["id"]

    harness.run_jobs()

    state = harness.client.get(f"/jobs/{prepare_id}").json()
    assert (state["stage"], state["outcome"]) == ("failed", "internal")
    assert temp_files(harness) == []


def test_an_abandoned_half_prepared_folder_is_swept(harness):
    abandoned = harness.rt.temp.reserve("abandoned")
    (abandoned / "video.part").write_bytes(b"half")

    harness.clock.advance(15 * 60 + 61)
    harness.client.get("/files/anything")

    assert not abandoned.exists()


@pytest.mark.parametrize("option", ["360p", "thumbnail"])
def test_options_that_dont_need_preparing_are_refused(harness, option):
    inspect_id = harness.inspected(URL, MERGEABLE)

    assert harness.client.post(f"/jobs/{inspect_id}/prepare/{option}").status_code == 409
