import pytest
from conftest import audio_only, media, video

from fetchall.extractor import ExtractionFailed, Outcome

YT = "https://www.youtube.com/watch?v=abc"
OTHER = "https://video.example/watch/1"
IP = "203.0.113.42"
DAY = 24 * 3600
MB = 1_000_000
PROXY = "http://user-session-{session}:secret@gw.proxy.test:823"

blocked = ExtractionFailed(Outcome.BLOCKED, "The site is temporarily blocking fetchall.")


@pytest.fixture
def harness(make_harness):
    return make_harness(proxy_url=PROXY)


def youtube_media(**overrides):
    formats = (
        video(1080, audio=False, size=90 * MB),
        video(720, audio=False, size=60 * MB),
        video(360, size=20 * MB),
        audio_only(size=5 * MB),
    )
    return media(*formats, site="Youtube", url=YT, **overrides)


def inspect(harness, url=YT, ip=IP) -> dict:
    response = harness.as_ip(ip).post("/jobs", json={"url": url})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    harness.run_jobs()
    return {"id": job_id, **harness.client.get(f"/jobs/{job_id}").json()}


def routes(harness, kind="inspect"):
    return [route for k, _, route in harness.extractor.routes if k == kind]


def server_blocked_proxy_ok(harness, url=YT, **overrides):
    harness.extractor.script[url] = blocked
    harness.extractor.proxy_script[url] = youtube_media(**overrides)


def test_a_blocked_youtube_job_is_retried_once_through_the_proxy(harness):
    server_blocked_proxy_ok(harness)

    state = inspect(harness)

    assert state["stage"] == "ready"
    assert routes(harness)[0] == "server"
    assert routes(harness)[1].startswith("proxy-")
    assert len(routes(harness)) == 2


def test_proxied_media_is_capped_and_says_why(harness):
    server_blocked_proxy_ok(harness)

    info = inspect(harness)["media"]

    assert [o["id"] for o in info["options"]] == ["720p", "360p", "audio"]
    assert "720p" in info["notice"]


def test_proxied_videos_over_the_proxy_duration_cap_are_blocked_with_a_hint(harness):
    server_blocked_proxy_ok(harness, duration=20 * 60)

    state = inspect(harness)

    assert (state["stage"], state["outcome"]) == ("failed", "blocked")
    assert "15 minutes" in state["message"]


@pytest.mark.parametrize("outcome", [o for o in Outcome if o != Outcome.BLOCKED])
def test_only_blocked_failures_are_retried(harness, outcome):
    harness.extractor.script[YT] = ExtractionFailed(outcome, "nope")

    state = inspect(harness)

    assert state["outcome"] == outcome.value
    assert routes(harness) == ["server"]


def test_sites_off_the_allowlist_are_never_proxied(harness):
    harness.extractor.script[OTHER] = blocked
    harness.extractor.proxy_script[OTHER] = media()

    state = inspect(harness, OTHER)

    assert state["outcome"] == "blocked"
    assert routes(harness) == ["server"]


@pytest.mark.parametrize("url", ["https://youtu.be/abc", "https://m.youtube.com/watch?v=abc"])
def test_the_allowlist_covers_youtube_domains(harness, url):
    server_blocked_proxy_ok(harness, url)

    assert inspect(harness, url)["stage"] == "ready"


def test_without_a_proxy_configured_blocked_jobs_fail_gracefully(make_harness):
    harness = make_harness()
    server_blocked_proxy_ok(harness)

    state = inspect(harness)

    assert (state["outcome"], routes(harness)) == ("blocked", ["server"])
    assert "temporarily" in state["message"]


def test_when_the_proxy_is_blocked_too_the_visitor_is_told_to_try_later(harness):
    harness.extractor.script[YT] = blocked
    harness.extractor.proxy_script[YT] = blocked

    state = inspect(harness)

    assert (state["outcome"], len(routes(harness))) == ("blocked", 2)
    assert "temporarily" in state["message"]


def test_each_visitor_gets_three_proxied_videos_a_day(harness):
    harness.clock.now = 1_700_000_000 - (1_700_000_000 % DAY)
    server_blocked_proxy_ok(harness)
    for _ in range(3):
        assert inspect(harness)["stage"] == "ready"

    assert inspect(harness)["outcome"] == "blocked"
    assert inspect(harness, ip="203.0.113.43")["stage"] == "ready"

    harness.clock.advance(DAY)
    assert inspect(harness)["stage"] == "ready"


def test_the_daily_byte_ceiling_switches_the_proxy_off_until_tomorrow(harness):
    harness.clock.now = 1_700_000_000 - (1_700_000_000 % DAY)
    server_blocked_proxy_ok(harness)
    harness.rt.proxy_budget.add_bytes(300 * MB)

    assert inspect(harness)["outcome"] == "blocked"
    assert routes(harness) == ["server"]

    harness.clock.advance(DAY)
    assert inspect(harness)["stage"] == "ready"


def test_proxied_media_is_never_handed_over_as_a_direct_link(harness):
    server_blocked_proxy_ok(harness)
    job = inspect(harness)

    plan = harness.client.get(f"/jobs/{job['id']}/downloads/360p").json()

    assert plan["delivery"] == "stream"


def test_preparing_proxied_media_downloads_through_the_same_session(harness):
    server_blocked_proxy_ok(harness)
    job = inspect(harness)
    proxy_route = routes(harness)[1]

    harness.as_ip(IP).post(f"/jobs/{job['id']}/prepare/720p")
    harness.run_jobs()

    assert routes(harness, "download") == [proxy_route]


def test_a_server_prepare_that_gets_blocked_falls_back_to_the_proxy(harness):
    harness.extractor.script[YT] = youtube_media()
    harness.extractor.downloads[YT] = blocked
    job = inspect(harness)

    prepare_id = harness.as_ip(IP).post(f"/jobs/{job['id']}/prepare/720p").json()["id"]
    harness.run_jobs()

    assert harness.client.get(f"/jobs/{prepare_id}").json()["stage"] == "ready"
    first, second = routes(harness, "download")
    assert (first, second.startswith("proxy-")) == ("server", True)


def test_a_blocked_prepare_above_the_proxy_caps_suggests_a_lower_quality(harness):
    harness.extractor.script[YT] = youtube_media()
    harness.extractor.downloads[YT] = blocked
    job = inspect(harness)

    prepare_id = harness.as_ip(IP).post(f"/jobs/{job['id']}/prepare/1080p").json()["id"]
    harness.run_jobs()

    state = harness.client.get(f"/jobs/{prepare_id}").json()
    assert (state["stage"], state["outcome"]) == ("failed", "blocked")
    assert "720p or lower" in state["message"]
    assert routes(harness, "download") == ["server"]


def test_the_tier_used_is_logged(harness):
    server_blocked_proxy_ok(harness)

    job = inspect(harness)

    entry = next(e for e in harness.rt.joblog.entries() if e["id"] == job["id"])
    assert entry["tier"] == "proxy"


def test_proxy_settings_default_to_the_spec():
    from fetchall.config import Settings

    s = Settings()
    assert s.proxy_url is None
    assert s.proxy_domains == ["youtube.com", "youtu.be"]
    assert (s.proxy_max_height, s.proxy_max_duration_seconds) == (720, 900)
    assert (s.proxy_max_filesize_bytes, s.proxy_jobs_per_ip_per_day) == (200 * MB, 3)
    assert s.proxy_daily_bytes == 300 * MB
