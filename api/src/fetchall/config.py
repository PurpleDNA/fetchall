from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SALT = "dev-only-salt"


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
    environment: str = "development"
    ip_hash_salt: str = DEV_SALT
    job_log_path: str = "/tmp/fetchall-log/jobs.sqlite3"
    job_log_retention_seconds: int = 7 * 24 * 3600
    policy_file: str = "/config/policy.toml"

    prepare_timeout_seconds: int = 900
    temp_dir: str = "/tmp/fetchall"
    temp_file_ttl_seconds: int = 900
    temp_ceiling_bytes: int = 20_000_000_000
    sweep_interval_seconds: float = 60

    # Every worker request goes through the egress proxy; unset only for local runs outside Docker.
    egress_proxy_url: str | None = None
    pot_provider_url: str | None = None
    youtube_player_clients: list[str] = ["default", "mweb"]

    # Residential proxy URL with a {session} placeholder for sticky sessions; a secret.
    proxy_url: str | None = None
    proxy_domains: list[str] = ["youtube.com", "youtu.be"]
    proxy_max_height: int = 720
    proxy_max_duration_seconds: int = 900
    proxy_max_filesize_bytes: int = 200_000_000
    proxy_jobs_per_ip_per_day: int = 3
    proxy_daily_bytes: int = 300_000_000
    egress_host: str = "0.0.0.0"
    egress_port: int = 8888
    egress_max_bytes: int = 1_500_000_000
    egress_idle_timeout_seconds: float = 30
    egress_max_duration_seconds: float = 3600

    @model_validator(mode="after")
    def production_needs_a_real_salt(self) -> "Settings":
        if self.environment == "production" and self.ip_hash_salt == DEV_SALT:
            raise ValueError("FETCHALL_IP_HASH_SALT must be set to a secret in production")
        return self
