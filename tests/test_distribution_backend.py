from __future__ import annotations

import sqlite3
from pathlib import Path

from searchviewer.backend import ViewerBackend


SEARCHDB_ROOT = Path(__file__).resolve().parents[2] / "SearchDB"
DEMO_ROOT = SEARCHDB_ROOT / "tests" / ".tmp" / "local-docs-demo"
DEMO_CONFIG = DEMO_ROOT / "searchdb.local.yaml"
DEMO_DB = DEMO_ROOT / "searchdb.sqlite3"


def _run_count(db_path: Path) -> int:
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as con:
        return int(con.execute("SELECT count(*) FROM retrieval_runs").fetchone()[0])


def test_backend_uses_local_cached_db_for_distribution_settings(tmp_path: Path) -> None:
    shared_db = tmp_path / "shared.sqlite3"
    shared_db.write_bytes(DEMO_DB.read_bytes())
    settings_path = tmp_path / "SearchViewerSettings.yaml"
    settings_path.write_text(
        "\n".join(
            [
                f'shared_config_path: "{DEMO_CONFIG.as_posix()}"',
                f'shared_db_path: "{shared_db.as_posix()}"',
                f'local_cache_dir: "{(tmp_path / "cache").as_posix()}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    shared_before = _run_count(shared_db)

    backend = ViewerBackend(searchdb_root=SEARCHDB_ROOT, settings_path=settings_path)
    status = backend.status()
    payload = backend.search({"query": "G71", "top_k": 1, "query_type": "spec_question"})

    local_db = Path(status["distribution"]["local_cached_db_path"])
    assert status["distribution"]["enabled"] is True
    assert status["distribution"]["launcher_mode"] == "distribution"
    assert status["connection"]["db_path"] == str(local_db)
    assert status["connection"]["config_path"] == str(DEMO_CONFIG)
    assert payload["results"]
    assert _run_count(shared_db) == shared_before
    assert _run_count(local_db) == shared_before + 1


def test_status_reports_missing_distribution_settings_without_default_connect(tmp_path: Path) -> None:
    settings_path = tmp_path / "SearchViewerSettings.yaml"

    backend = ViewerBackend(searchdb_root=SEARCHDB_ROOT, settings_path=settings_path)
    status = backend.status()

    assert status["distribution"]["enabled"] is False
    assert status["distribution"]["settings_path"] == str(settings_path.resolve())
    assert status["distribution"]["error"]
    assert status["connection"]["mode"] == "disconnected"


def test_distribution_settings_can_supply_searchdb_working_dir_for_frozen_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.syspath_prepend(str(SEARCHDB_ROOT / "src"))
    shared_db = tmp_path / "shared.sqlite3"
    shared_db.write_bytes(DEMO_DB.read_bytes())
    settings_path = tmp_path / "SearchViewerSettings.yaml"
    settings_path.write_text(
        "\n".join(
            [
                f'shared_config_path: "{DEMO_CONFIG.as_posix()}"',
                f'shared_db_path: "{shared_db.as_posix()}"',
                f'local_cache_dir: "{(tmp_path / "cache").as_posix()}"',
                f'searchdb_working_dir: "{SEARCHDB_ROOT.as_posix()}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    backend = ViewerBackend(searchdb_root=tmp_path / "missing-searchdb", settings_path=settings_path)
    status = backend.status()

    assert status["distribution"]["enabled"] is True
    assert status["distribution"]["searchdb_working_dir"] == str(SEARCHDB_ROOT)
    assert status["connection"]["mode"] == "config"
    assert status["connection"]["summary"]["documents"] > 0
