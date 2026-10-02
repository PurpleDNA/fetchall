from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FETCHALL_", env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]
    queue_name: str = "fetchall"

    inspect_timeout_seconds: int = 60
    job_ttl_seconds: int = 3600
    sse_poll_seconds: float = 0.5
    sse_max_seconds: float = 300

    max_concurrent_jobs: int = 2
    max_queued_jobs: int = 20
    jobs_per_ip_per_hour: int = 10
    max_height: int = 1080
    max_duration_seconds: int = 3600
    max_filesize_bytes: int = 1_000_000_000
    ip_hash_salt: str = "dev-only-salt"
    policy_file: str = "/config/policy.toml"

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
