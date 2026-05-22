from __future__ import annotations

from types import SimpleNamespace

from searchviewer.launcher import EmbeddedServer, build_local_url, find_free_port, smoke_check


def test_find_free_port_and_build_local_url() -> None:
    port = find_free_port()

    assert isinstance(port, int)
    assert 0 < port < 65536
    assert build_local_url(port) == f"http://127.0.0.1:{port}"


def test_embedded_server_stop_sets_stop_flag() -> None:
    server = EmbeddedServer(app_factory=lambda: None, port=12345)
    fake_server = SimpleNamespace(should_exit=False)
    server.server = fake_server

    server.stop()

    assert server.stopped is True
    assert fake_server.should_exit is True


def test_smoke_check_reports_missing_settings(tmp_path) -> None:
    payload = smoke_check(settings_path=tmp_path / "missing.yaml")

    assert payload["ok"] is False
    assert payload["settings"]["exists"] is False
    assert payload["static"]["exists"] in {True, False}
