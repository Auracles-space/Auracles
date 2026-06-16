"""Tests for the ClamAV scan entrypoint.

In production clamd runs as a separate service (it holds a ~1GB+ signature
database that must stay off the artifact worker). A remote daemon cannot see
the worker's filesystem, so file bytes are streamed over TCP via INSTREAM. A
single-host/local setup may still use the Unix-socket daemon.
"""

import sys
import types

import pytest

from app.workers.tasks import artifacts


def test_scan_streams_bytes_to_network_clamd_when_host_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """With CLAMAV_HOST set, the file is streamed to the remote daemon (INSTREAM)."""
    sample = tmp_path / "upload.bin"
    sample.write_bytes(b"infected-bytes")

    captured: dict = {}

    class FakeNetworkSocket:
        def __init__(self, host: str, port: int) -> None:
            captured["host"] = host
            captured["port"] = port

        def instream(self, fileobj) -> dict:
            captured["streamed"] = fileobj.read()
            return {"stream": ("FOUND", "Eicar-Test-Signature")}

    fake_clamd = types.SimpleNamespace(ClamdNetworkSocket=FakeNetworkSocket)
    monkeypatch.setitem(sys.modules, "clamd", fake_clamd)
    monkeypatch.setattr(
        artifacts,
        "get_settings",
        lambda: types.SimpleNamespace(clamav_host="auracles-clamav", clamav_port=3310),
    )

    result = artifacts.scan_file_with_clamav(str(sample))

    assert result == "infected"
    assert captured["host"] == "auracles-clamav"
    assert captured["port"] == 3310
    assert captured["streamed"] == b"infected-bytes"


def test_scan_uses_unix_socket_when_no_host_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Without CLAMAV_HOST, fall back to the local Unix-socket daemon (path scan)."""
    sample = tmp_path / "upload.bin"
    sample.write_bytes(b"clean-bytes")

    class FakeUnixSocket:
        def scan(self, path: str) -> dict:
            return {path: ("OK", None)}

    monkeypatch.setitem(
        sys.modules, "clamd", types.SimpleNamespace(ClamdUnixSocket=FakeUnixSocket)
    )
    monkeypatch.setattr(
        artifacts,
        "get_settings",
        lambda: types.SimpleNamespace(clamav_host=None, clamav_port=3310),
    )

    assert artifacts.scan_file_with_clamav(str(sample)) == "clean"
