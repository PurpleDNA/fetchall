import pytest

from fetchall.extractor import Outcome
from fetchall.failures import MESSAGES, classify

REAL_ERRORS = [
    (
        "ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser",
        Outcome.BLOCKED,
    ),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", Outcome.BLOCKED),
    ("ERROR: [twitter] 1: HTTP Error 429: Too Many Requests", Outcome.BLOCKED),
    ("ERROR: [youtube] abc: This content isn't available, try again later.", Outcome.BLOCKED),
    (
        "ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate",
        Outcome.LOGIN_REQUIRED,
    ),
    (
        "ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
        Outcome.LOGIN_REQUIRED,
    ),
    (
        "ERROR: [youtube] abc: Join this channel to get access to members-only content",
        Outcome.LOGIN_REQUIRED,
    ),
    (
        "ERROR: [vimeo] 1084537: The web client only works when logged-in. Use --cookies",
        Outcome.LOGIN_REQUIRED,
    ),
    (
        "ERROR: [instagram] x: Requested content is not available, rate-limit reached or login required",
        Outcome.BLOCKED,
    ),
    (
        "ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader",
        Outcome.NOT_FOUND,
    ),
    ("ERROR: [reddit] x: HTTP Error 404: Not Found", Outcome.NOT_FOUND),
    ("ERROR: [youtube] abc: This video is no longer available", Outcome.NOT_FOUND),
    ("ERROR: [youtube] xxxxxxxxxxx: This video is unavailable", Outcome.NOT_FOUND),
    (
        "ERROR: [generic] Unable to download webpage: Unsupported URL: https://example.com/",
        Outcome.NO_MEDIA,
    ),
    ("ERROR: [twitter] 1: No video could be found in this tweet", Outcome.NO_MEDIA),
    ("ERROR: [Netflix] x: This video is DRM protected", Outcome.DRM),
    (
        "ERROR: [bbc] x: This video is not available in your country due to geo restriction",
        Outcome.UNSUPPORTED,
    ),
    ("ERROR: [youtube] abc: This live event will begin in 3 hours.", Outcome.UNSUPPORTED),
    ("ERROR: HTTP Error 403: Blocked by fetchall egress policy", Outcome.UNSUPPORTED),
    (
        "ERROR: Unable to connect to proxy: Tunnel connection failed: 403 Blocked by fetchall egress policy",
        Outcome.UNSUPPORTED,
    ),
    ("ERROR: something nobody has seen before", Outcome.INTERNAL),
]


@pytest.mark.parametrize(("error", "outcome"), REAL_ERRORS)
def test_classifies_real_yt_dlp_errors(error, outcome):
    assert classify(error).outcome == outcome


def test_the_message_never_leaks_the_raw_error():
    failure = classify("ERROR: [youtube] secret-id: HTTP Error 403: Forbidden")

    assert "secret-id" not in failure.message
    assert failure.message == MESSAGES[Outcome.BLOCKED]


def test_every_outcome_has_its_own_message():
    assert set(MESSAGES) == set(Outcome)
    assert len(set(MESSAGES.values())) == len(Outcome)
