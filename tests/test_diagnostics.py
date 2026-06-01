from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from searchviewer.app import create_app
from searchviewer.backend import ViewerBackend
from searchviewer.frontend import inspect_static_bundle, static_error_html


SEARCHDB_ROOT = Path(__file__).resolve().parents[2] / "SearchDB"


def _write_static_bundle(root: Path, *, include_css: bool = True) -> None:
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "index.html").write_text(
        "\n".join(
            [
                "<!doctype html>",
                "<html><head>",
                '<script type="module" src="/assets/app.js"></script>',
                '<link rel="stylesheet" href="/assets/app.css">',
                "</head><body><div id=\"root\"></div></body></html>",
            ]
        ),
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log('ok');", encoding="utf-8")
    if include_css:
        (assets / "app.css").write_text("body { color: #111; }", encoding="utf-8")


def _backend(tmp_path: Path) -> ViewerBackend:
    return ViewerBackend(searchdb_root=SEARCHDB_ROOT, settings_path=tmp_path / "missing.yaml")


def test_static_bundle_inspection_reports_missing_referenced_assets(tmp_path: Path) -> None:
    _write_static_bundle(tmp_path, include_css=False)

    report = inspect_static_bundle(tmp_path)

    assert report["ok"] is False
    assert report["index_exists"] is True
    assert "/assets/app.css" in report["missing_assets"]
    assert "/assets/app.js" not in report["missing_assets"]


def test_static_error_html_names_missing_assets(tmp_path: Path) -> None:
    _write_static_bundle(tmp_path, include_css=False)
    report = inspect_static_bundle(tmp_path)

    html = static_error_html(report)

    assert "SearchViewer static bundle is incomplete" in html
    assert "/assets/app.css" in html
    assert str(tmp_path) in html


def test_create_app_serves_static_assets_when_bundle_is_complete(tmp_path: Path, monkeypatch) -> None:
    _write_static_bundle(tmp_path)
    monkeypatch.setattr("searchviewer.app.static_dir", lambda: tmp_path)
    client = TestClient(create_app(backend=_backend(tmp_path)))

    root = client.get("/")
    script = client.get("/assets/app.js")
    style = client.get("/assets/app.css")
    status = client.get("/api/status")

    assert root.status_code == 200
    assert script.status_code == 200
    assert style.status_code == 200
    assert status.status_code == 200


def test_create_app_returns_diagnostic_page_when_static_bundle_is_incomplete(tmp_path: Path, monkeypatch) -> None:
    _write_static_bundle(tmp_path, include_css=False)
    monkeypatch.setattr("searchviewer.app.static_dir", lambda: tmp_path)
    client = TestClient(create_app(backend=_backend(tmp_path)))

    root = client.get("/")
    asset = client.get("/assets/app.css")
    status = client.get("/api/status")

    assert root.status_code == 503
    assert asset.status_code == 503
    assert "SearchViewer static bundle is incomplete" in root.text
    assert "/assets/app.css" in root.text
    assert status.status_code == 200


def test_client_log_endpoint_accepts_local_json_and_omits_unapproved_fields(
    tmp_path: Path,
    caplog,
) -> None:
    client = TestClient(create_app(backend=_backend(tmp_path)), client=("127.0.0.1", 50000))
    caplog.set_level(logging.INFO, logger="searchviewer.client")

    response = client.post(
        "/api/client-log",
        json={
            "type": "error",
            "message": "startup failed",
            "source": "window.error",
            "query": "SECRET_QUERY",
            "text_body": "SECRET_TEXT",
        },
    )

    assert response.status_code == 204
    assert "startup failed" in caplog.text
    assert "SECRET_QUERY" not in caplog.text
    assert "SECRET_TEXT" not in caplog.text


def test_client_log_endpoint_rejects_oversized_payload(tmp_path: Path) -> None:
    client = TestClient(create_app(backend=_backend(tmp_path)), client=("127.0.0.1", 50000))

    response = client.post("/api/client-log", content=b"x" * 5000)

    assert response.status_code == 413


def test_smoke_output_file_is_written(tmp_path: Path) -> None:
    from searchviewer.launcher import main

    output_path = tmp_path / "smoke.json"
    exit_code = main(
        [
            "--smoke",
            "--settings",
            str(tmp_path / "missing.yaml"),
            "--smoke-output",
            str(output_path),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["settings"]["exists"] is False
    assert payload["static"]["index_exists"] in {True, False}
