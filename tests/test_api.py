from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from searchviewer.app import create_app
from searchviewer.backend import ViewerBackend


SEARCHDB_ROOT = Path(__file__).resolve().parents[2] / "SearchDB"
DEMO_ROOT = SEARCHDB_ROOT / "tests" / ".tmp" / "local-docs-demo"
DEMO_CONFIG = DEMO_ROOT / "searchdb.local.yaml"
DEMO_DB = DEMO_ROOT / "searchdb.sqlite3"


def test_api_status_and_search_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "searchdb.sqlite3"
    shutil.copy2(DEMO_DB, db_path)
    backend = ViewerBackend(searchdb_root=SEARCHDB_ROOT)
    backend.connect({"config_path": str(DEMO_CONFIG), "db_path": str(db_path)})
    client = TestClient(create_app(backend=backend))

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["searchdb_importable"] is True

    search = client.post(
        "/api/search",
        json={"query": "G71", "top_k": 3, "query_type": "spec_question"},
    )
    assert search.status_code == 200
    payload = search.json()
    assert payload["results"]

    chunk = client.get(f"/api/chunks/{payload['results'][0]['chunk_id']}")
    assert chunk.status_code == 200
    assert chunk.json()["text_body"]


def test_api_disconnected_state_does_not_surface_internal_500(tmp_path: Path) -> None:
    backend = ViewerBackend(searchdb_root=SEARCHDB_ROOT, settings_path=tmp_path / "missing.yaml")
    client = TestClient(create_app(backend=backend))

    runs = client.get("/api/runs")
    search = client.post("/api/search", json={"query": "G71", "top_k": 3})
    chunk = client.get("/api/chunks/1")

    assert runs.status_code == 200
    assert runs.json() == []
    assert search.status_code == 400
    assert "no database is connected" in search.json()["detail"]
    assert chunk.status_code == 400
    assert "no database is connected" in chunk.json()["detail"]
