from redis import Redis
from rq import Worker

from fetchall.config import Settings


def main() -> None:
    """Run an RQ worker. RQ forks a fresh process for every job."""
    settings = Settings()
    Worker([settings.queue_name], connection=Redis.from_url(settings.redis_url)).work()


if __name__ == "__main__":
    main()
