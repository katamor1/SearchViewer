from __future__ import annotations

from fastapi.testclient import TestClient

from searchviewer.app import create_app


def test_api_status_and_search_flow() -> None:
    client = TestClient(create_app())

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
