import pytest

from fetchall.extractor import ExtractionFailed, Outcome
from fetchall.ytdlp import YtDlpExtractor, normalise

GOOGLEVIDEO = "https://rr1.googlevideo.com/videoplayback?expire=1&ip=203.0.113.9&itag="


def youtube_info(**overrides):
    info = {
        "id": "abc",
        "title": "A talk",
        "webpage_url": "https://www.youtube.com/watch?v=abc",
        "extractor_key": "Youtube",
        "uploader": "Speaker",
        "duration": 300,
        "thumbnail": "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
        "age_limit": 0,
        "formats": [
            {
                "format_id": "sb0",
                "format_note": "storyboard",
                "ext": "mhtml",
                "vcodec": "none",
                "acodec": "none",
                "protocol": "mhtml",
                "url": "https://x",
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "filesize": 4_000_000,
                "protocol": "https",
                "url": GOOGLEVIDEO + "140",
            },
            {
                "format_id": "18",
                "ext": "mp4",
                "height": 360,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "filesize_approx": 9_000_000,
                "protocol": "https",
                "url": GOOGLEVIDEO + "18",
            },
            {
                "format_id": "137",
                "ext": "mp4",
                "height": 1080,
                "vcodec": "avc1",
                "acodec": "none",
                "filesize": 50_000_000,
                "protocol": "https",
                "url": GOOGLEVIDEO + "137",
            },
            {
                "format_id": "hls-720",
                "ext": "mp4",
                "height": 720,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "protocol": "m3u8_native",
                "url": "https://m.example/a.m3u8",
            },
        ],
    }
    return {**info, **overrides}


def test_normalises_metadata():
    media = normalise(youtube_info())

    assert (media.title, media.site, media.uploader, media.duration, media.age_limit) == (
        "A talk",
        "Youtube",
        "Speaker",
        300,
        0,
    )
    assert media.url == "https://www.youtube.com/watch?v=abc"


def test_drops_storyboards_and_describes_each_format():
    formats = {f.id: f for f in normalise(youtube_info()).formats}

    assert set(formats) == {"140", "18", "137", "hls-720"}
    assert (formats["140"].has_video, formats["140"].has_audio) == (False, True)
    assert (formats["137"].height, formats["137"].has_audio) == (1080, False)
    assert formats["18"].filesize == 9_000_000  # falls back to the approximate size
    assert formats["18"].single_file and not formats["hls-720"].single_file
    assert all(f.ip_bound for f in formats.values())  # YouTube URLs are tied to the IP


def test_ip_bound_is_detected_from_the_url_on_other_sites():
    info = youtube_info(
        extractor_key="Example",
        formats=[
            {
                "format_id": "a",
                "ext": "mp4",
                "height": 720,
                "url": "https://cdn.example/v?ip=1.2.3.4",
            },
            {"format_id": "b", "ext": "mp4", "height": 480, "url": "https://cdn.example/v.mp4"},
        ],
    )

    bound = {f.id: f.ip_bound for f in normalise(info).formats}

    assert bound == {"a": True, "b": False}


def test_unknown_codecs_are_treated_as_a_complete_file():
    info = youtube_info(
        extractor_key="Generic",
        formats=None,
        url="https://site.example/clip.mp4",
        ext="mp4",
    )

    (only,) = normalise(info).formats

    assert (only.has_video, only.has_audio, only.single_file) == (True, True, True)


def test_playlists_are_refused():
    with pytest.raises(ExtractionFailed) as e:
        normalise({"_type": "playlist", "title": "Mix", "entries": []})

    assert e.value.outcome == Outcome.UNSUPPORTED


def test_a_page_without_media_is_no_media():
    with pytest.raises(ExtractionFailed) as e:
        normalise(youtube_info(formats=[]))

    assert e.value.outcome == Outcome.NO_MEDIA


def test_drm_only_media_is_drm():
    drm = [{"format_id": "x", "ext": "mp4", "height": 720, "has_drm": True, "url": "https://x"}]

    with pytest.raises(ExtractionFailed) as e:
        normalise(youtube_info(formats=drm))

    assert e.value.outcome == Outcome.DRM


def test_routes_every_request_through_the_egress_proxy():
    extractor = YtDlpExtractor(proxy="http://egress:8888")

    assert extractor._options["proxy"] == "http://egress:8888"


def test_youtube_uses_the_po_token_provider_and_less_checked_clients():
    extractor = YtDlpExtractor(
        pot_provider_url="http://bgutil:4416", youtube_player_clients=["default", "mweb"]
    )

    assert extractor._options["extractor_args"] == {
        "youtube": {"player_client": ["default", "mweb"]},
        "youtubepot-bgutilhttp": {"base_url": ["http://bgutil:4416"]},
    }


def test_the_po_token_plugin_is_installed():
    from yt_dlp.extractor.youtube.pot.provider import _pot_providers
    from yt_dlp.plugins import load_all_plugins

    load_all_plugins()

    assert "BgUtilHTTP" in _pot_providers.value
