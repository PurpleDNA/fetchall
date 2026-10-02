import ipaddress
from ipaddress import IPv4Address, IPv6Address

NAT64 = ipaddress.ip_network("64:ff9b::/96")

PLAIN_HTTP_PORT = 80
TUNNEL_PORT = 443


def is_public(ip: IPv4Address | IPv6Address) -> bool:
    if isinstance(ip, IPv6Address):
        # IPv6 forms that embed an IPv4 address are judged by the address they carry.
        if ip.ipv4_mapped:
            return is_public(ip.ipv4_mapped)
        if ip in NAT64:
            return is_public(IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.sixtofour or ip.teredo:
            return False
    return ip.is_global and not ip.is_multicast
