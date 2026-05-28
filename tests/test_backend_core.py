from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from searchviewer.backend import ViewerBackend


SEARCHDB_ROOT = Path(__file__).resolve().parents[2] / "SearchDB"
DEMO_ROOT = SEARCHDB_ROOT / "tests" / ".tmp" / "local-docs-demo"
DEMO_CONFIG = DEMO_ROOT / "searchdb.local.yaml"
DEMO_DB = DEMO_ROOT / "searchdb.sqlite3"


def _backend_with_writable_demo_db(
    tmp_path: Path,
    *,
    opener=None,
) -> ViewerBackend:
    db_path = tmp_path / "searchdb.sqlite3"
    shutil.copy2(DEMO_DB, db_path)
    backend = ViewerBackend(searchdb_root=SEARCHDB_ROOT, opener=opener)
    backend.connect({"config_path": str(DEMO_CONFIG), "db_path": str(db_path)})
    return backend


def test_default_connection_uses_local_docs_demo_profile_when_available() -> None:
    backend = ViewerBackend(searchdb_root=SEARCHDB_ROOT)

    status = backend.status()

    assert status["searchdb_importable"] is True
    assert status["default_profile"]["available"] is True
    assert status["connection"]["config_path"] == str(DEMO_CONFIG)
    assert status["connection"]["db_path"] == str(DEMO_DB)
    assert status["connection"]["root_linking_enabled"] is True
    assert status["connection"]["summary"]["documents"] > 0


def test_search_with_config_returns_ranked_results_and_run_metadata(tmp_path: Path) -> None:
    backend = _backend_with_writable_demo_db(tmp_path)

    payload = backend.search(
        {
            "query": "G71",
            "top_k": 5,
            "query_type": "spec_question",
            "include_path": None,
            "exclude_path": None,
            "since": None,
        }
    )

    assert payload["status"] == "completed"
    assert payload["ranking_profile"] == "fts5_metadata_v1"
    assert payload["warnings"] == []
    assert payload["results"]
    assert payload["results"][0]["display_path"]
    assert payload["results"][0]["ranking_reasons"]


def test_db_only_search_is_allowed_but_warns_and_disables_file_links(tmp_path: Path) -> None:
    db_path = tmp_path / "searchdb.sqlite3"
    shutil.copy2(DEMO_DB, db_path)
    backend = ViewerBackend(searchdb_root=SEARCHDB_ROOT)
    connection = backend.connect({"db_path": str(db_path), "config_path": None})

    payload = backend.search({"query": "G71", "top_k": 3, "query_type": "spec_question"})

    assert connection["config_path"] is None
    assert connection["root_linking_enabled"] is False
    assert "DBのみモード" in " ".join(payload["warnings"])
    assert payload["results"]
    assert payload["results"][0]["can_open_file"] is False


def test_chunk_detail_includes_text_and_document_metadata(tmp_path: Path) -> None:
    backend = _backend_with_writable_demo_db(tmp_path)
    payload = backend.search({"query": "G71", "top_k": 1, "query_type": "spec_question"})
    chunk_id = payload["results"][0]["chunk_id"]

    detail = backend.chunk_detail(chunk_id)

    assert detail["chunk_id"] == chunk_id
    assert detail["text_body"]
    assert detail["document"]["document_id"] == payload["results"][0]["document_id"]
    assert detail["document"]["display_path"] == payload["results"][0]["display_path"]


def test_open_document_resolves_only_known_documents_under_config_root(tmp_path: Path) -> None:
    opened: list[str] = []
    backend = _backend_with_writable_demo_db(tmp_path, opener=lambda path: opened.append(str(path)))
    payload = backend.search({"query": "G71", "top_k": 1, "query_type": "spec_question"})
    document_id = payload["results"][0]["document_id"]

    result = backend.open_document(document_id)

    assert result["opened"] is True
    assert opened
    assert Path(opened[0]).is_absolute()
    assert result["target_path"] == opened[0]


def test_open_document_is_rejected_without_root_resolution() -> None:
    backend = ViewerBackend(searchdb_root=SEARCHDB_ROOT)
    backend.connect({"db_path": str(DEMO_DB), "config_path": None})

    with pytest.raises(PermissionError):
        backend.open_document(1)
