from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from searchviewer.distribution import (
    copy_shared_database_to_cache,
    load_distribution_settings,
    read_cache_metadata,
)


SEARCHDB_ROOT = Path(__file__).resolve().parents[2] / "SearchDB"
DEMO_ROOT = SEARCHDB_ROOT / "tests" / ".tmp" / "local-docs-demo"
DEMO_CONFIG = DEMO_ROOT / "searchdb.local.yaml"
DEMO_DB = DEMO_ROOT / "searchdb.sqlite3"


def _write_settings(path: Path, shared_db: Path, cache_dir: Path) -> None:
    path.write_text(
        "\n".join(
            [
                f'shared_config_path: "{DEMO_CONFIG.as_posix()}"',
                f'shared_db_path: "{shared_db.as_posix()}"',
                f'local_cache_dir: "{cache_dir.as_posix()}"',
                'copy_policy: "if_source_changed"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_load_distribution_settings_resolves_paths_relative_to_settings_file(tmp_path: Path) -> None:
    settings_path = tmp_path / "SearchViewerSettings.yaml"
    shared_db = tmp_path / "shared" / "searchdb.sqlite3"
    cache_dir = tmp_path / "cache"
    shared_db.parent.mkdir()
    shared_db.write_bytes(b"sqlite bytes")
    settings_path.write_text(
        "\n".join(
            [
                f'shared_config_path: "{DEMO_CONFIG.as_posix()}"',
                'shared_db_path: "shared/searchdb.sqlite3"',
                'local_cache_dir: "cache"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_distribution_settings(settings_path)

    assert settings.settings_path == settings_path.resolve()
    assert settings.shared_config_path == DEMO_CONFIG
    assert settings.shared_db_path == shared_db.resolve()
    assert settings.local_db_path == (cache_dir / "searchdb.sqlite3").resolve()
    assert settings.copy_policy == "if_source_changed"


def test_copy_shared_database_to_cache_copies_db_and_records_metadata(tmp_path: Path) -> None:
    shared_db = tmp_path / "shared.sqlite3"
    cache_dir = tmp_path / "cache"
    settings_path = tmp_path / "SearchViewerSettings.yaml"
    shared_db.write_bytes(DEMO_DB.read_bytes())
    _write_settings(settings_path, shared_db, cache_dir)
    settings = load_distribution_settings(settings_path)

    status = copy_shared_database_to_cache(settings)

    assert status["copied"] is True
    assert settings.local_db_path.exists()
    assert settings.local_db_path.read_bytes() == shared_db.read_bytes()
    metadata = read_cache_metadata(settings.local_db_path)
    assert metadata["shared_db_path"] == str(shared_db.resolve())
    assert metadata["shared_size"] == shared_db.stat().st_size


def test_copy_shared_database_to_cache_recopies_when_source_changes(tmp_path: Path) -> None:
    shared_db = tmp_path / "shared.sqlite3"
    cache_dir = tmp_path / "cache"
    settings_path = tmp_path / "SearchViewerSettings.yaml"
    shared_db.write_bytes(b"first")
    _write_settings(settings_path, shared_db, cache_dir)
    settings = load_distribution_settings(settings_path)
    copy_shared_database_to_cache(settings)

    shared_db.write_bytes(b"second-version")
    status = copy_shared_database_to_cache(settings)

    assert status["copied"] is True
    assert settings.local_db_path.read_bytes() == b"second-version"
    assert read_cache_metadata(settings.local_db_path)["shared_size"] == len(b"second-version")


def test_local_cache_database_can_be_written_without_touching_shared_db(tmp_path: Path) -> None:
    shared_db = tmp_path / "shared.sqlite3"
    cache_dir = tmp_path / "cache"
    settings_path = tmp_path / "SearchViewerSettings.yaml"
    shared_db.write_bytes(DEMO_DB.read_bytes())
    _write_settings(settings_path, shared_db, cache_dir)
    settings = load_distribution_settings(settings_path)
    copy_shared_database_to_cache(settings)

    with sqlite3.connect(settings.local_db_path) as con:
        con.execute("CREATE TABLE IF NOT EXISTS local_probe(value TEXT)")
        con.execute("INSERT INTO local_probe(value) VALUES ('ok')")
    with sqlite3.connect(f"file:{shared_db.as_posix()}?mode=ro", uri=True) as con:
        names = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    assert "local_probe" not in names
