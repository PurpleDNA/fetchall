from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError

from fetchall.config import Settings


def create_app(settings: Settings | None = None, redis: Redis | None = None) -> FastAPI:
    settings = settings or Settings()
    if redis is None:
        redis = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)

    app = FastAPI(title="fetchall")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        try:
            redis.ping()
        except RedisError:
            return JSONResponse({"status": "degraded", "redis": "unreachable"}, status_code=503)
        return {"status": "ok", "redis": "ok"}

    return app
