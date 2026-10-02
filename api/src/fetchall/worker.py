from rq import Worker

from fetchall import runtime


def main() -> None:
    """Run an RQ worker. RQ forks a fresh process for every job, with a hard timeout."""
    rt = runtime.current()
    Worker([rt.queue], connection=rt.redis).work()


if __name__ == "__main__":
    main()
