import pytest
from conftest import audio_only, media, video

URL = "https://video.example/watch/1"


def plan(harness, job_id, option):
    return harness.client.get(f"/jobs/{job_id}/downloads/{option}")


def test_a_plain_public_file_is_handed_over_as_a_direct_link(harness):
    job_id = harness.inspected(URL, media(video(720)))

    response = plan(harness, job_id, "720p")

    assert response.json() == {
        "delivery": "direct",
        "url": "https://cdn.example/v720a.mp4",
        "filename": "A short film (720p).mp4",
    }


def test_an_ip_bound_file_is_streamed_through_the_server(harness):
    job_id = harness.inspected(URL, media(video(720, ip_bound=True)))
    harness.upstream.serve(
        "https://cdn.example/v720a.mp4", b"movie-bytes", **{"content-type": "video/mp4"}
    )

    body = plan(harness, job_id, "720p").json()
    file = harness.client.get(body["url"])

    assert body["delivery"] == "stream"
    assert body["url"] == f"/jobs/{job_id}/files/720p"
    assert file.status_code == 200
    assert file.content == b"movie-bytes"
    assert file.headers["content-type"] == "video/mp4"
    assert file.headers["content-length"] == "11"
    assert file.headers["content-disposition"] == (
        'attachment; filename="A short film (720p).mp4"; '
        "filename*=UTF-8''A%20short%20film%20%28720p%29.mp4"
    )


def test_streaming_sends_the_headers_the_site_expects(harness):
    job_id = harness.inspected(URL, media(video(720, ip_bound=True)))
    harness.upstream.serve("https://cdn.example/v720a.mp4", b"x")

    harness.client.get(f"/jobs/{job_id}/files/720p")

    assert harness.upstream.requests[-1].headers["user-agent"] == "yt-dlp-ua"


def test_a_file_needing_headers_the_browser_cannot_send_is_streamed(harness):
    needs_referer = video(720, headers={"Referer": "https://video.example/"})
    job_id = harness.inspected(URL, media(needs_referer))

    assert plan(harness, job_id, "720p").json()["delivery"] == "stream"


def test_resuming_a_streamed_download_forwards_the_range(harness):
    job_id = harness.inspected(URL, media(video(720, ip_bound=True)))
    harness.upstream.serve("https://cdn.example/v720a.mp4", b"0123456789")

    file = harness.client.get(f"/jobs/{job_id}/files/720p", headers={"Range": "bytes=4-7"})

    assert file.status_code == 206
    assert file.content == b"4567"
    assert file.headers["content-range"] == "bytes 4-7/10"


def test_audio_only_keeps_its_m4a_container(harness):
    job_id = harness.inspected(URL, media(video(720), audio_only(ip_bound=True)))
    harness.upstream.serve("https://cdn.example/a.m4a", b"sound")

    body = plan(harness, job_id, "audio").json()

    assert (body["delivery"], body["filename"]) == ("stream", "A short film.m4a")
    assert harness.client.get(body["url"]).content == b"sound"


def test_the_thumbnail_is_streamed_with_a_proper_filename(harness):
    job_id = harness.inspected(URL, media())
    harness.upstream.serve("https://video.example/thumb.jpg", b"jpeg")

    body = plan(harness, job_id, "thumbnail").json()
    file = harness.client.get(body["url"])

    assert body["filename"] == "A short film.jpg"
    assert file.content == b"jpeg"


@pytest.mark.parametrize(
    "formats",
    [
        (video(1080, audio=False), audio_only()),
        (video(720, single_file=False),),
    ],
    ids=["needs-merge", "segmented"],
)
def test_formats_that_need_processing_are_prepared_on_the_server(harness, formats):
    job_id = harness.inspected(URL, media(*formats))
    option = harness.client.get(f"/jobs/{job_id}").json()["media"]["options"][0]["id"]

    body = plan(harness, job_id, option).json()

    assert body["delivery"] == "prepare"
    assert body["filename"].endswith(".mp4")
    assert harness.client.get(f"/jobs/{job_id}/files/{option}").status_code == 404


def test_a_site_refusing_the_file_is_a_bad_gateway(harness):
    job_id = harness.inspected(URL, media(video(720, ip_bound=True)))
    harness.upstream.serve("https://cdn.example/v720a.mp4", b"", status=403)

    assert harness.client.get(f"/jobs/{job_id}/files/720p").status_code == 502


def test_unknown_options_are_not_found(harness):
    job_id = harness.inspected(URL, media())

    assert plan(harness, job_id, "4320p").status_code == 404


def test_planning_before_inspection_finishes_is_a_conflict(harness):
    harness.extractor.script[URL] = media()
    job_id = harness.inspect(URL)

    assert plan(harness, job_id, "720p").status_code == 409
