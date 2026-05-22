from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from searchviewer.distribution import copy_shared_database_to_cache, load_distribution_settings


DEFAULT_QUERY_TYPE = "spec_question"
DEFAULT_TOP_K = 10


def _default_searchdb_root() -> Path:
    return Path(__file__).resolve().parents[3] / "SearchDB"


def _default_opener(path: Path) -> None:
    os.startfile(str(path))  # type: ignore[attr-defined]


@contextmanager
def _pushd(path: Path):
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


class ViewerBackend:
    def __init__(
        self,
        *,
        searchdb_root: Path | str | None = None,
        opener: Callable[[Path], None] | None = None,
        settings_path: Path | str | None = None,
    ) -> None:
        self.searchdb_root = Path(searchdb_root or _default_searchdb_root()).resolve()
        self.searchdb_src = self.searchdb_root / "src"
        self.default_config = self.searchdb_root / "tests" / ".tmp" / "local-docs-demo" / "searchdb.local.yaml"
        self.default_db = self.searchdb_root / "tests" / ".tmp" / "local-docs-demo" / "searchdb.sqlite3"
        self._opener = opener or _default_opener
        self.settings_path = Path(settings_path).expanduser().resolve() if settings_path is not None else None
        self._config_working_dir: Path | None = None
        self._searchdb_importable = self._ensure_searchdb_importable()
        self.distribution: dict[str, Any] = self._initial_distribution_status()
        self.connection: dict[str, Any] = {
            "config_path": None,
            "db_path": None,
            "root_linking_enabled": False,
            "roots": {},
            "mode": "disconnected",
            "warnings": [],
        }
        if self.settings_path is not None:
            self._connect_distribution_profile()
        elif self.default_config.exists() and self.default_db.exists():
            self.connect({"config_path": str(self.default_config), "db_path": str(self.default_db)})

    def _ensure_searchdb_importable(self) -> bool:
        if self.searchdb_src.exists():
            src_text = str(self.searchdb_src)
            if src_text not in sys.path:
                sys.path.insert(0, src_text)
        try:
            import searchdb  # noqa: F401
        except ImportError:
            return False
        return True

    def _require_searchdb(self) -> None:
        if not self._searchdb_importable:
            raise RuntimeError(f"SearchDB package is not importable from {self.searchdb_src}")

    def status(self) -> dict[str, Any]:
        return {
            "searchdb_root": str(self.searchdb_root),
            "searchdb_importable": self._searchdb_importable,
            "default_profile": {
                "available": self.default_config.exists() and self.default_db.exists(),
                "config_path": str(self.default_config),
                "db_path": str(self.default_db),
            },
            "connection": self._public_connection(),
            "distribution": self._public_distribution(),
        }

    def _initial_distribution_status(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "launcher_mode": "distribution" if self.settings_path is not None else "development",
            "settings_path": str(self.settings_path) if self.settings_path is not None else None,
            "shared_config_path": None,
            "shared_db_path": None,
            "searchdb_working_dir": None,
            "local_cached_db_path": None,
            "copy_policy": None,
            "cache_fresh": False,
            "last_copied_at_utc": None,
            "cache": None,
            "error": None,
        }

    def _connect_distribution_profile(self) -> None:
        assert self.settings_path is not None
        if not self.settings_path.exists():
            self.distribution["error"] = f"SearchViewerSettings.yaml not found: {self.settings_path}"
            return

        try:
            settings = load_distribution_settings(self.settings_path)
            self._config_working_dir = settings.searchdb_working_dir
            cache_info = copy_shared_database_to_cache(settings)
            self.connect(
                {
                    "config_path": str(settings.shared_config_path),
                    "db_path": str(settings.local_db_path),
                }
            )
            metadata = cache_info.get("metadata") or {}
            self.distribution.update(
                {
                    "enabled": True,
                    "settings_path": str(settings.settings_path),
                    "shared_config_path": str(settings.shared_config_path),
                    "shared_db_path": str(settings.shared_db_path),
                    "searchdb_working_dir": str(settings.searchdb_working_dir)
                    if settings.searchdb_working_dir
                    else None,
                    "local_cached_db_path": str(settings.local_db_path),
                    "copy_policy": settings.copy_policy,
                    "cache_fresh": True,
                    "last_copied_at_utc": metadata.get("copied_at_utc"),
                    "cache": cache_info,
                    "error": None,
                }
            )
        except Exception as exc:  # surface startup errors through /api/status instead of crashing the launcher.
            self.distribution["error"] = str(exc)

    def connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_searchdb()
        config_path = self._optional_path(payload.get("config_path"))
        db_path = self._optional_path(payload.get("db_path"))

        roots: dict[str, Path] = {}
        warnings: list[str] = []
        if config_path is not None:
            config = self._load_config(config_path)
            if db_path is None:
                db_path = config.db.path
            roots = {root.id: root.path.resolve() for root in config.roots}
        elif db_path is None:
            raise ValueError("db_path is required when config_path is not supplied")
        else:
            warnings.append(
                "DBのみモード: SearchDB config、readiness guard、synonyms、ファイルroot解決は無効です。"
            )

        assert db_path is not None
        db_path = db_path.resolve()
        summary = self._summarize_db(db_path)
        root_linking_enabled = bool(config_path and roots)
        self.connection = {
            "config_path": str(config_path) if config_path else None,
            "db_path": str(db_path),
            "root_linking_enabled": root_linking_enabled,
            "roots": roots,
            "mode": "config" if config_path else "db_only",
            "warnings": warnings,
            "summary": summary,
        }
        result = self._public_connection()
        return result

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_searchdb()
        db_path = self._connected_db_path()
        query = str(payload.get("query") or "").strip()
        top_k = int(payload.get("top_k") or DEFAULT_TOP_K)
        query_type = str(payload.get("query_type") or DEFAULT_QUERY_TYPE)
        include_path = self._empty_to_none(payload.get("include_path"))
        exclude_path = self._empty_to_none(payload.get("exclude_path"))
        since = self._empty_to_none(payload.get("since"))

        from searchdb.config import DbConfig
        from searchdb.db import connect
        from searchdb.query import load_aliases
        from searchdb.ranking import get_run_payload, retrieve
        from searchdb.schema import apply_migrations, validate_runtime

        aliases: dict[str, tuple[str, ...]] = {}
        if self.connection["config_path"]:
            config = self._load_config(Path(self.connection["config_path"]))
            config = replace(config, db=DbConfig(path=db_path))
            from searchdb.access_guard import ensure_runtime_access_allowed

            ensure_runtime_access_allowed(config, command="retrieve")
            aliases = load_aliases(config.curation.synonyms_path)

        con = connect(db_path)
        try:
            apply_migrations(con)
            validate_runtime(con)
            run_id = retrieve(
                con,
                query_text=query,
                query_type=query_type,
                top_k=top_k,
                aliases=aliases,
                include_path=include_path,
                exclude_path=exclude_path,
                since=since,
            )
            result = get_run_payload(con, run_id)
            result["warnings"] = list(self.connection["warnings"])
            result["results"] = [self._decorate_result(row) for row in result["results"]]
            return result
        finally:
            con.close()

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        db_path = self._connected_db_path()
        with self._connect_readonly(db_path) as con:
            return [
                dict(row)
                for row in con.execute(
                    """
                    SELECT
                      r.run_id,
                      r.query_id,
                      q.query_text,
                      q.query_type,
                      r.top_k,
                      r.search_mode,
                      r.ranking_profile,
                      r.status,
                      r.started_at_utc,
                      r.finished_at_utc,
                      count(rr.result_id) AS result_count
                    FROM retrieval_runs r
                    JOIN queries q ON q.query_id = r.query_id
                    LEFT JOIN retrieval_results rr ON rr.run_id = r.run_id
                    GROUP BY r.run_id
                    ORDER BY r.run_id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]

    def run_payload(self, run_id: int) -> dict[str, Any]:
        self._require_searchdb()
        from searchdb.db import connect
        from searchdb.ranking import get_run_payload

        db_path = self._connected_db_path()
        con = connect(db_path)
        try:
            result = get_run_payload(con, run_id)
            result["warnings"] = list(self.connection["warnings"])
            result["results"] = [self._decorate_result(row) for row in result["results"]]
            return result
        finally:
            con.close()

    def chunk_detail(self, chunk_id: int) -> dict[str, Any]:
        db_path = self._connected_db_path()
        with self._connect_readonly(db_path) as con:
            row = con.execute(
                """
                SELECT
                  c.chunk_id,
                  c.document_id,
                  c.version_id,
                  c.chunk_index,
                  c.title,
                  c.source_section,
                  c.text_body,
                  c.char_start,
                  c.char_end,
                  c.token_estimate,
                  c.extraction_kind,
                  c.language_hint,
                  d.source_root,
                  d.normalized_path,
                  d.display_path,
                  d.archive_path,
                  d.extension,
                  d.mime_type,
                  d.size_bytes,
                  d.mtime_utc,
                  d.ctime_utc,
                  d.sha256,
                  d.is_archive_member,
                  d.authority_level,
                  d.manual_importance,
                  d.known_noise,
                  d.label_rationale
                FROM chunks c
                JOIN documents d ON d.document_id = c.document_id
                WHERE c.chunk_id = ?
                """,
                (chunk_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"chunk not found: {chunk_id}")
        data = dict(row)
        document_keys = {
            "document_id",
            "source_root",
            "normalized_path",
            "display_path",
            "archive_path",
            "extension",
            "mime_type",
            "size_bytes",
            "mtime_utc",
            "ctime_utc",
            "sha256",
            "is_archive_member",
            "authority_level",
            "manual_importance",
            "known_noise",
            "label_rationale",
        }
        document = {key: data.pop(key) for key in list(data.keys()) if key in document_keys}
        document["can_open_file"] = self._resolve_document_target(document) is not None
        data["document"] = document
        return data

    def open_document(self, document_id: int) -> dict[str, Any]:
        db_path = self._connected_db_path()
        with self._connect_readonly(db_path) as con:
            row = con.execute(
                """
                SELECT
                  document_id,
                  source_root,
                  normalized_path,
                  display_path,
                  archive_path,
                  is_archive_member
                FROM documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"document not found: {document_id}")

        target = self._resolve_document_target(dict(row))
        if target is None:
            raise PermissionError("現在のconfig root配下に文書パスを解決できません。")
        self._opener(target)
        return {"opened": True, "target_path": str(target), "document_id": document_id}

    def _decorate_result(self, result: dict[str, Any]) -> dict[str, Any]:
        document = self._document_for_result(result["document_id"])
        decorated = dict(result)
        decorated["document"] = document
        decorated["can_open_file"] = self._resolve_document_target(document) is not None
        return decorated

    def _document_for_result(self, document_id: int) -> dict[str, Any]:
        db_path = self._connected_db_path()
        with self._connect_readonly(db_path) as con:
            row = con.execute(
                """
                SELECT
                  document_id,
                  source_root,
                  normalized_path,
                  display_path,
                  archive_path,
                  extension,
                  mime_type,
                  size_bytes,
                  mtime_utc,
                  sha256,
                  is_archive_member,
                  authority_level,
                  manual_importance,
                  known_noise,
                  label_rationale
                FROM documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"document not found: {document_id}")
        return dict(row)

    def _resolve_document_target(self, document: dict[str, Any]) -> Path | None:
        if not self.connection.get("root_linking_enabled"):
            return None
        roots: dict[str, Path] = self.connection.get("roots", {})
        root = roots.get(str(document.get("source_root")))
        if root is None:
            return None

        display_path = str(document.get("display_path") or "")
        outer_display_path = display_path.split("::", 1)[0]
        if not outer_display_path:
            return None

        root_resolved = root.resolve()
        target = (root_resolved / outer_display_path).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            return None
        if not target.exists():
            return None
        return target

    def _load_config(self, config_path: Path):
        from searchdb.config import load_config

        config_path = config_path.resolve()
        if self._config_working_dir is not None:
            working_dir = self._config_working_dir
            if not working_dir.exists():
                raise FileNotFoundError(f"searchdb_working_dir not found: {working_dir}")
        elif self.searchdb_root.exists():
            working_dir = self.searchdb_root
        else:
            working_dir = config_path.parent
        with _pushd(working_dir):
            return load_config(config_path)

    def _summarize_db(self, db_path: Path) -> dict[str, int]:
        with self._connect_readonly(db_path) as con:
            return {
                "documents": int(con.execute("SELECT count(*) FROM documents").fetchone()[0]),
                "chunks": int(con.execute("SELECT count(*) FROM chunks").fetchone()[0]),
                "retrieval_runs": int(con.execute("SELECT count(*) FROM retrieval_runs").fetchone()[0]),
                "retrieval_results": int(con.execute("SELECT count(*) FROM retrieval_results").fetchone()[0]),
            }

    @contextmanager
    def _connect_readonly(self, db_path: Path):
        if not db_path.exists():
            raise FileNotFoundError(f"database not found: {db_path}")
        uri = f"file:{db_path.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    def _connected_db_path(self) -> Path:
        db_path = self.connection.get("db_path")
        if not db_path:
            raise RuntimeError("no database is connected")
        return Path(db_path)

    def _public_connection(self) -> dict[str, Any]:
        roots: dict[str, Path] = self.connection.get("roots", {})
        return {
            "config_path": self.connection.get("config_path"),
            "db_path": self.connection.get("db_path"),
            "root_linking_enabled": bool(self.connection.get("root_linking_enabled")),
            "mode": self.connection.get("mode"),
            "warnings": list(self.connection.get("warnings", [])),
            "roots": {key: str(path) for key, path in roots.items()},
            "summary": self.connection.get("summary"),
        }

    def _public_distribution(self) -> dict[str, Any]:
        return dict(self.distribution)

    @staticmethod
    def _empty_to_none(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _optional_path(value: Any) -> Path | None:
        text = ViewerBackend._empty_to_none(value)
        return Path(text).expanduser() if text else None
