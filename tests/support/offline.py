"""The offline suite's network guard (D50): loopback and Unix sockets only, so `make check`
can never depend on, or leak to, anything outside the machine."""

import ipaddress
import socket
from typing import Any

import pytest

LOCAL_NAMES = {"localhost", "localhost.localdomain", ""}


class NetworkBlocked(RuntimeError):
    """An offline test tried to reach the network."""


def _is_local(host: object) -> bool:
    if not isinstance(host, str) or host in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every connection and name lookup that is not on this machine, for one test."""
    connect, lookup = socket.socket.connect, socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
            raise NetworkBlocked(f"offline test tried to reach {address[0]}")
        connect(self, address)

    def guarded_lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_local(host.decode() if isinstance(host, bytes) else host):
            raise NetworkBlocked(f"offline test tried to resolve {host}")
        return lookup(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_lookup)
