import secrets
from urllib.parse import urlsplit, urlunsplit

SERVER = "server"
PROXY_PREFIX = "proxy-"


def new_proxy_route() -> str:
    return f"{PROXY_PREFIX}{secrets.token_hex(8)}"


def is_proxy(route: str) -> bool:
    return route.startswith(PROXY_PREFIX)


def egress_url(egress: str, route: str) -> str:
    if route == SERVER:
        return egress
    parts = urlsplit(egress)
    return urlunsplit(parts._replace(netloc=f"{route}:x@{parts.netloc}"))
