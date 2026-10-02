import pytest

from fetchall.delivery import content_disposition, filename_for


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Big Buck Bunny", "Big Buck Bunny (720p).mp4"),
        ('AC/DC: "Live" <at> River|Plate?*', "AC DC Live at River Plate (720p).mp4"),
        ("line\nbreak\ttab\x00null", "line break tab null (720p).mp4"),
        ("...hidden.", "hidden (720p).mp4"),
        ("", "video (720p).mp4"),
        ("x" * 300, "x" * 120 + " (720p).mp4"),
        ("Café 🎬 日本語", "Café 🎬 日本語 (720p).mp4"),
    ],
)
def test_filenames_are_safe_on_every_os(title, expected):
    assert filename_for(title, "720p", "mp4") == expected


def test_content_disposition_has_an_ascii_fallback_and_utf8_name():
    assert content_disposition("Café 🎬.mp4") == (
        "attachment; filename=\"Caf .mp4\"; filename*=UTF-8''Caf%C3%A9%20%F0%9F%8E%AC.mp4"
    )
