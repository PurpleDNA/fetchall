from rq.worker_pool import WorkerPool

from fetchall import runtime


def main() -> None:
    rt = runtime.current()
    WorkerPool([rt.queue], connection=rt.redis, num_workers=rt.settings.max_concurrent_jobs).start()


if __name__ == "__main__":
    main()
