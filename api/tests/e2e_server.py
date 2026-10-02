import fakeredis
import httpx2
import uvicorn
from conftest import FakeExtractor, FakeUpstream, audio_only, media, video
from rq import Queue

from fetchall import runtime
from fetchall.app import create_app
from fetchall.config import Settings

E2E_LINK = "https://video.example/watch/1"


def build_app():
    extractor, upstream = FakeExtractor(), FakeUpstream()
    extractor.script[E2E_LINK] = media(video(720, ip_bound=True, size=11), audio_only(size=5))
    upstream.serve("https://cdn.example/v720a.mp4", b"movie-bytes", **{"content-type": "video/mp4"})
    upstream.serve("https://video.example/thumb.jpg", b"jpeg", **{"content-type": "image/jpeg"})

    redis = fakeredis.FakeRedis()
    rt = runtime.build(
        Settings(cors_origins=["http://localhost:5174"]),
        redis=redis,
        extractor=extractor,
        http_transport=httpx2.MockTransport(upstream.handle),
    )
    rt.queue = Queue(rt.settings.queue_name, connection=redis, is_async=False)
    runtime.set_current(rt)
    return create_app(rt)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8001, log_level="warning")
