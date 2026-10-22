"""The offline suite cannot reach the network: a test that tries fails at once and says why."""

import socket

import pytest

from tests.support.offline import NetworkBlocked


def test_a_connection_to_the_internet_is_refused() -> None:
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("192.0.2.1", 443), timeout=0.2)  # TEST-NET-1, never routed


def test_a_name_lookup_for_a_remote_host_is_refused() -> None:
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("example.com", 443)


def test_loopback_stays_open_for_postgres_and_local_servers() -> None:
    server = socket.create_server(("127.0.0.1", 0))
    with server, socket.create_connection(server.getsockname(), timeout=1):
        pass
