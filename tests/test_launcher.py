from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from searchviewer.launcher import (
    EmbeddedServer,
    build_local_url,
    find_free_port,
    smoke_check,
    start_server_and_open_browser,
)


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


def test_embedded_server_disables_uvicorn_log_config(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, app, **kwargs) -> None:
            captured["app"] = app
            captured.update(kwargs)

    class FakeServer:
        def __init__(self, config) -> None:
            self.config = config
            self.should_exit = False
            self.started = True

        def run(self) -> None:
            return None

    monkeypatch.setattr("searchviewer.launcher.uvicorn.Config", FakeConfig)
    monkeypatch.setattr("searchviewer.launcher.uvicorn.Server", FakeServer)

    server = EmbeddedServer(app_factory=lambda: object(), port=12345)
    server.start()
    assert server.thread is not None
    server.thread.join(timeout=5)

    assert captured["log_config"] is None
    assert captured["access_log"] is False


def test_start_server_timeout_does_not_open_browser() -> None:
    opened: list[str] = []

    class FakeServer:
        url = "http://127.0.0.1:12345"

        def start(self) -> None:
            return None

        def wait_until_started(self) -> bool:
            return False

    started = start_server_and_open_browser(FakeServer(), open_browser=opened.append)

    assert started is False
    assert opened == []


def test_smoke_check_reports_missing_settings(tmp_path) -> None:
    payload = smoke_check(settings_path=tmp_path / "missing.yaml")

    assert payload["ok"] is False
    assert payload["settings"]["exists"] is False
    assert payload["static"]["exists"] in {True, False}
    assert payload["static"]["index_exists"] in {True, False}


@pytest.mark.skipif(os.name != "nt", reason="UNC path parsing is Windows-specific")
def test_smoke_check_parses_unc_style_settings_without_touching_share(tmp_path) -> None:
    settings_path = tmp_path / "SearchViewerSettings.yaml"
    settings_path.write_text(
        "\n".join(
            [
                'shared_config_path: "\\\\\\\\server\\\\share\\\\SearchDB\\\\searchdb.local.yaml"',
                'shared_db_path: "\\\\\\\\server\\\\share\\\\SearchDB\\\\searchdb.sqlite3"',
                f'local_cache_dir: "{(tmp_path / "cache").as_posix()}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    payload = smoke_check(settings_path=settings_path)

    assert payload["settings"]["valid"] is True
    assert payload["settings"]["shared_config_exists"] is False
    assert payload["settings"]["shared_db_exists"] is False
