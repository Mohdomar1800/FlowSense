"""Launcher: a port taken by another program is reported immediately instead of after the startup timeout."""

import socket
import time

import flowsense


def test_busy_port_is_reported_without_starting_a_server(monkeypatch):
    monkeypatch.setattr(flowsense, "is_flowsense", lambda url: False)  # the other program isn't FlowSense
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other_program:
        other_program.bind(("127.0.0.1", 0))
        other_program.listen()
        port = other_program.getsockname()[1]

        started = time.monotonic()
        embedded, error = flowsense.connect_or_start(f"http://127.0.0.1:{port}")

    assert embedded is None
    assert f"Port {port} is already used" in error
    assert time.monotonic() - started < 5  # not the 30 s startup timeout


def test_free_port_is_not_reported_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert not flowsense.port_in_use("127.0.0.1", port)
