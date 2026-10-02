import ipaddress

import pytest

from fetchall.egress.policy import is_public

BLOCKED = [
    "127.0.0.1",
    "10.0.0.5",
    "172.16.3.4",
    "192.168.1.1",
    "169.254.169.254",
    "100.64.0.1",
    "0.0.0.0",
    "255.255.255.255",
    "224.0.0.251",
    "240.0.0.1",
    "192.0.0.8",
    "198.18.0.1",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd12:3456::1",
    "ff02::1",
    "::ffff:127.0.0.1",
    "::ffff:169.254.169.254",
    "64:ff9b::a00:1",
    "64:ff9b::a9fe:a9fe",
    "2002:a00:1::",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",
]

ALLOWED = ["8.8.8.8", "142.250.180.14", "2606:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808"]


@pytest.mark.parametrize("address", BLOCKED)
def test_non_public_addresses_are_refused(address):
    assert not is_public(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ALLOWED)
def test_public_addresses_are_allowed(address):
    assert is_public(ipaddress.ip_address(address))
