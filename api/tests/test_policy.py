import pytest
from conftest import audio_only, media, video

URL = "https://video.example/watch/1"


def state_of(harness, url: str, media_info=None) -> dict:
    harness.extractor.script[url] = media_info or media(url=url)
    job_id = harness.inspect(url)
    harness.run_jobs()
    return {"id": job_id, **harness.client.get(f"/jobs/{job_id}").json()}


def assert_unavailable(state: dict) -> None:
    assert (state["stage"], state["outcome"], state["message"]) == (
        "failed",
        "unsupported",
        "This content is unavailable.",
    )


def test_a_blocked_url_is_unavailable_without_being_fetched(harness):
    harness.write_policy(f'blocked_urls = ["{URL}"]')

    state = state_of(harness, URL)

    assert_unavailable(state)
    assert harness.extractor.inspect_calls == []


def test_url_matching_ignores_trailing_slashes_fragments_and_host_case(harness):
    harness.write_policy('blocked_urls = ["https://video.example/watch/1"]')

    assert_unavailable(state_of(harness, "https://VIDEO.example/watch/1/#t=10"))


@pytest.mark.parametrize(
    ("url", "blocked"),
    [
        ("https://blocked.example/v/1", True),
        ("https://m.blocked.example/v/1", True),
        ("https://notblocked.example/v/1", False),
        ("https://blocked.example.evil.test/v/1", False),
    ],
)
def test_a_blocked_domain_covers_its_subdomains_only(harness, url, blocked):
    harness.write_policy('blocked_domains = ["blocked.example"]')

    state = state_of(harness, url)

    assert (state["stage"] == "failed") is blocked


@pytest.mark.parametrize("uploader", ["Someone", "UC123", "https://video.example/@someone"])
def test_a_blocked_uploader_is_caught_after_extraction(harness, uploader):
    harness.write_policy(f'blocked_uploaders = ["{uploader}"]')
    info = media(uploader_id="UC123", uploader_url="https://video.example/@someone")

    assert_unavailable(state_of(harness, URL, info))


def test_the_canonical_url_is_checked_too(harness):
    harness.write_policy('blocked_urls = ["https://video.example/watch/1"]')
    info = media(url="https://video.example/watch/1")

    assert_unavailable(state_of(harness, "https://short.example/abc", info))


def test_the_blocklist_reloads_without_a_restart(harness):
    assert state_of(harness, URL)["stage"] == "ready"

    harness.write_policy(f'blocked_urls = ["{URL}"]')
    assert_unavailable(state_of(harness, URL))

    harness.write_policy("blocked_urls = []")
    assert state_of(harness, URL)["stage"] == "ready"


def test_blocking_after_inspection_stops_the_download(harness):
    job = state_of(harness, URL)

    harness.write_policy('blocked_uploaders = ["Someone"]')

    response = harness.client.get(f"/jobs/{job['id']}/downloads/720p")
    assert (response.status_code, response.json()["detail"]) == (
        404,
        "This content is unavailable.",
    )


def test_an_invalid_policy_file_keeps_the_previous_policy(harness):
    harness.write_policy(f'blocked_urls = ["{URL}"]')
    assert_unavailable(state_of(harness, URL))

    harness.write_policy("blocked_urls = [unterminated")

    assert_unavailable(state_of(harness, URL))


def test_ordinary_media_has_no_age_gate(harness):
    job = state_of(harness, URL)

    assert job["media"]["age_restricted"] is False
    assert harness.client.get(f"/jobs/{job['id']}/downloads/720p").status_code == 200


@pytest.mark.parametrize(
    ("url", "age_limit", "policy"),
    [
        ("https://video.example/watch/1", 18, ""),
        ("https://www.adult.example/view/1", 0, 'adult_domains = ["adult.example"]'),
    ],
    ids=["age-limit", "adult-domain"],
)
def test_adult_media_needs_confirmation_before_any_download(harness, url, age_limit, policy):
    harness.write_policy(policy)
    info = media(
        video(720, ip_bound=True),
        video(1080, audio=False),
        audio_only(),
        age_limit=age_limit,
        url=url,
    )
    job = state_of(harness, url, info)
    base = f"/jobs/{job['id']}"

    assert job["media"]["age_restricted"] is True
    for path in (f"{base}/downloads/720p", f"{base}/files/720p", f"{base}/downloads/thumbnail"):
        refused = harness.client.get(path)
        assert (refused.status_code, refused.json()["detail"]) == (403, "age_confirmation_required")
    assert harness.client.post(f"{base}/prepare/1080p").status_code == 403

    plan = harness.client.get(f"{base}/downloads/720p?age_confirmed=true").json()
    assert plan["url"] == f"{base}/files/720p?age_confirmed=true"
    harness.upstream.serve("https://cdn.example/v720a.mp4", b"bytes")
    assert harness.client.get(plan["url"]).status_code == 200
    assert harness.client.post(f"{base}/prepare/1080p?age_confirmed=true").status_code == 202
