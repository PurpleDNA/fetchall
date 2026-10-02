from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from FETCHALL_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="FETCHALL_", env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    # Browser origins allowed to call the API (the frontend). JSON list in the environment.
    cors_origins: list[str] = ["http://localhost:5173"]
    queue_name: str = "fetchall"

    # Hard limit on an inspect job; the worker kills it after this.
    inspect_timeout_seconds: int = 60
    # How long job state and progress events are kept in Redis.
    job_ttl_seconds: int = 3600
    # How often an open progress stream checks for new events.
    sse_poll_seconds: float = 0.5
