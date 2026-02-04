from __future__ import annotations

import http.client
import socket
import time

from gdrive_assistant_bot.health import start_health_server


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_STATUS_OK = 200
_STATUS_NOT_FOUND = 404


def _wait_for_health(port: int) -> None:
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
            conn.request("GET", "/healthz")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status == _STATUS_OK:
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("health server did not start")


def test_health_server_responds() -> None:
    port = _get_free_port()
    start_health_server("127.0.0.1", port, component="test")
    _wait_for_health(port)

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()

    assert resp.status == _STATUS_OK
    assert body == "ok\n"


def test_health_server_not_found() -> None:
    port = _get_free_port()
    start_health_server("127.0.0.1", port, component="test")
    _wait_for_health(port)

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
    conn.request("GET", "/missing")
    resp = conn.getresponse()
    resp.read()
    conn.close()

    assert resp.status == _STATUS_NOT_FOUND
