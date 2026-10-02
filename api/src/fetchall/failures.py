import re

from fetchall.egress.proxy import REFUSAL_PHRASE
from fetchall.extractor import ExtractionFailed, Outcome

MESSAGES = {
    Outcome.BLOCKED: "The site is temporarily blocking fetchall. Try again in a while.",
    Outcome.LOGIN_REQUIRED: "This needs a login to watch, which fetchall doesn't support.",
    Outcome.NOT_FOUND: "That video doesn't exist or was removed.",
    Outcome.NO_MEDIA: "No downloadable video was found at that link.",
    Outcome.DRM: "This video is DRM-protected, so fetchall can't download it.",
    Outcome.TOO_LARGE: "This video is too large for fetchall.",
    Outcome.UNSUPPORTED: "fetchall can't download this link.",
    Outcome.INTERNAL: "Something went wrong fetching that link. Try again in a moment.",
}

# First match wins: bot checks must come before generic "sign in" login rules.
RULES: list[tuple[Outcome, str | None, list[str]]] = [
    (
        Outcome.UNSUPPORTED,
        "That address isn't on the public internet.",
        [re.escape(REFUSAL_PHRASE)],
    ),
    (Outcome.BLOCKED, None, ["not a bot", "HTTP Error 429", "Too Many Requests", "rate.?limit"]),
    (Outcome.BLOCKED, None, ["try again later", "temporarily unavailable", "HTTP Error 403"]),
    (Outcome.DRM, None, [r"\bDRM\b"]),
    (
        Outcome.LOGIN_REQUIRED,
        None,
        [
            "confirm your age",
            "private video",
            "video is private",
            "members[- ]only",
            "join this channel",
            "login required",
            "log ?in",
            "logged-in",
            "sign in",
            "requires authentication",
            "account credentials",
            "--cookies",
            "registered users",
        ],
    ),
    (
        Outcome.UNSUPPORTED,
        "This video isn't available in the region fetchall runs from.",
        ["geo.?restrict", "not available in your (?:country|region)"],
    ),
    (
        Outcome.UNSUPPORTED,
        "Live streams and premieres can't be downloaded until they've finished.",
        ["live event will begin", "premieres in", "is (?:currently )?live", "UserNotLive"],
    ),
    (
        Outcome.NOT_FOUND,
        None,
        [
            "video (?:is )?unavailable",
            "no longer available",
            "has been removed",
            "was deleted",
            "does not exist",
            "HTTP Error 404",
            "HTTP Error 410",
            "not found",
            "terminated",
        ],
    ),
    (
        Outcome.NO_MEDIA,
        None,
        [
            "Unsupported URL",
            "No video formats found",
            "no video could be found",
            "no media found",
            "There's no video",
            "does not contain a video",
        ],
    ),
]

COMPILED = [
    (outcome, message, re.compile("|".join(alternatives), re.IGNORECASE))
    for outcome, message, alternatives in RULES
]


def classify(error: str) -> ExtractionFailed:
    for outcome, message, pattern in COMPILED:
        if pattern.search(error):
            return ExtractionFailed(outcome, message or MESSAGES[outcome])
    return ExtractionFailed(Outcome.INTERNAL, MESSAGES[Outcome.INTERNAL])
