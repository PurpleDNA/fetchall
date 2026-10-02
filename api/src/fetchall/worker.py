from rq import Worker

from fetchall import runtime


def main() -> None:
    rt = runtime.current()
    Worker([rt.queue], connection=rt.redis).work()


if __name__ == "__main__":
    main()
