import asyncio
import logging
import time

from redis import Redis

from fetchall.config import Settings
from fetchall.egress.proxy import EgressProxy
from fetchall.proxybudget import ProxyBudget


async def serve(settings: Settings) -> None:
    budget = ProxyBudget(Redis.from_url(settings.redis_url), settings, time.time)
    proxy = EgressProxy(
        upstream_for=budget.upstream_for,
        proxy_allowed=budget.allowed,
        on_proxy_bytes=budget.add_bytes,
        max_bytes=settings.egress_max_bytes,
        idle_timeout=settings.egress_idle_timeout_seconds,
        max_duration=settings.egress_max_duration_seconds,
    )
    server = await asyncio.start_server(proxy.handle, settings.egress_host, settings.egress_port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(Settings()))
