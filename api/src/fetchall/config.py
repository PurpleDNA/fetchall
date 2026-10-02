from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FETCHALL_", env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]
    queue_name: str = "fetchall"

    inspect_timeout_seconds: int = 60
    job_ttl_seconds: int = 3600
    sse_poll_seconds: float = 0.5

    prepare_timeout_seconds: int = 900
    temp_dir: str = "/tmp/fetchall"
    temp_file_ttl_seconds: int = 900
    temp_ceiling_bytes: int = 20_000_000_000
    sweep_interval_seconds: float = 60

    # Every worker request goes through the egress proxy; unset only for local runs outside Docker.
    egress_proxy_url: str | None = None
    egress_host: str = "0.0.0.0"
    egress_port: int = 8888
    egress_max_bytes: int = 1_500_000_000
    egress_idle_timeout_seconds: float = 30
    egress_max_duration_seconds: float = 3600
