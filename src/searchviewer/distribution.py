from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


COPY_POLICIES = {"if_source_changed", "if_missing", "always"}


@dataclass(frozen=True)
class DistributionSettings:
    settings_path: Path
    shared_config_path: Path
    shared_db_path: Path
    local_cache_dir: Path
    searchdb_working_dir: Path | None = None
    local_db_name: str = "searchdb.sqlite3"
    copy_policy: str = "if_source_changed"

    @property
    def local_db_path(self) -> Path:
        return self.local_cache_dir / self.local_db_name


def default_settings_path() -> Path:
    executable = Path(os.sys.executable).resolve()
    if getattr(os.sys, "frozen", False):
        return executable.with_name("SearchViewerSettings.yaml")
    return Path.cwd() / "SearchViewerSettings.yaml"


def _resolve_path(value: str, base_dir: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _default_cache_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SearchViewer" / "cache"
    return Path.home() / "AppData" / "Local" / "SearchViewer" / "cache"


def load_distribution_settings(path: str | Path) -> DistributionSettings:
    settings_path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("SearchViewerSettings.yaml must be a mapping")

    base_dir = settings_path.parent
    shared_config = raw.get("shared_config_path")
    shared_db = raw.get("shared_db_path")
    if not isinstance(shared_config, str) or not shared_config.strip():
        raise ValueError("shared_config_path is required")
    if not isinstance(shared_db, str) or not shared_db.strip():
        raise ValueError("shared_db_path is required")

    working_dir = raw.get("searchdb_working_dir")
    if working_dir is None or working_dir == "":
        searchdb_working_dir = None
    elif isinstance(working_dir, str):
        searchdb_working_dir = _resolve_path(working_dir, base_dir)
    else:
        raise ValueError("searchdb_working_dir must be a string when supplied")

    local_cache = raw.get("local_cache_dir")
    if local_cache is None:
        local_cache_dir = _default_cache_dir().resolve()
    elif isinstance(local_cache, str) and local_cache.strip():
        local_cache_dir = _resolve_path(local_cache, base_dir)
    else:
        raise ValueError("local_cache_dir must be a non-empty string when supplied")

    local_db_name = raw.get("local_db_name", "searchdb.sqlite3")
    if not isinstance(local_db_name, str) or not local_db_name.strip():
        raise ValueError("local_db_name must be a non-empty string")
    if Path(local_db_name).name != local_db_name:
        raise ValueError("local_db_name must be a file name, not a path")

    copy_policy = raw.get("copy_policy", "if_source_changed")
    if copy_policy not in COPY_POLICIES:
        raise ValueError(f"copy_policy must be one of: {', '.join(sorted(COPY_POLICIES))}")

    return DistributionSettings(
        settings_path=settings_path,
        shared_config_path=_resolve_path(shared_config, base_dir),
        shared_db_path=_resolve_path(shared_db, base_dir),
        local_cache_dir=local_cache_dir,
        searchdb_working_dir=searchdb_working_dir,
        local_db_name=local_db_name,
        copy_policy=str(copy_policy),
    )


def _metadata_path(local_db_path: Path) -> Path:
    return local_db_path.with_name(f"{local_db_path.name}.metadata.json")


def read_cache_metadata(local_db_path: str | Path) -> dict[str, Any]:
    metadata_path = _metadata_path(Path(local_db_path))
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _write_cache_metadata(settings: DistributionSettings) -> dict[str, Any]:
    source_stat = settings.shared_db_path.stat()
    payload = {
        "shared_db_path": str(settings.shared_db_path),
        "local_db_path": str(settings.local_db_path),
        "shared_size": source_stat.st_size,
        "shared_mtime_ns": source_stat.st_mtime_ns,
        "copied_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _metadata_path(settings.local_db_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def _source_signature(settings: DistributionSettings) -> dict[str, Any]:
    stat = settings.shared_db_path.stat()
    return {
        "shared_db_path": str(settings.shared_db_path),
        "shared_size": stat.st_size,
        "shared_mtime_ns": stat.st_mtime_ns,
    }


def _needs_copy(settings: DistributionSettings) -> bool:
    if settings.copy_policy == "always":
        return True
    if not settings.local_db_path.exists():
        return True
    if settings.copy_policy == "if_missing":
        return False
    metadata = read_cache_metadata(settings.local_db_path)
    return any(metadata.get(key) != value for key, value in _source_signature(settings).items())


def _remove_local_sidecars(local_db_path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = local_db_path.with_name(f"{local_db_path.name}{suffix}")
        if sidecar.exists():
            sidecar.unlink()


def _copy_optional_wal(shared_db_path: Path, local_db_path: Path) -> None:
    source_wal = shared_db_path.with_name(f"{shared_db_path.name}-wal")
    local_wal = local_db_path.with_name(f"{local_db_path.name}-wal")
    if source_wal.exists() and source_wal.stat().st_size > 0:
        shutil.copy2(source_wal, local_wal)


def copy_shared_database_to_cache(settings: DistributionSettings) -> dict[str, Any]:
    if not settings.shared_db_path.exists():
        raise FileNotFoundError(f"shared_db_path not found: {settings.shared_db_path}")
    settings.local_cache_dir.mkdir(parents=True, exist_ok=True)

    copied = _needs_copy(settings)
    if copied:
        _remove_local_sidecars(settings.local_db_path)
        temp_path = settings.local_db_path.with_name(f"{settings.local_db_path.name}.tmp")
        shutil.copy2(settings.shared_db_path, temp_path)
        temp_path.replace(settings.local_db_path)
        _copy_optional_wal(settings.shared_db_path, settings.local_db_path)
        metadata = _write_cache_metadata(settings)
    else:
        metadata = read_cache_metadata(settings.local_db_path)

    return {
        "copied": copied,
        "settings_path": str(settings.settings_path),
        "shared_config_path": str(settings.shared_config_path),
        "shared_db_path": str(settings.shared_db_path),
        "searchdb_working_dir": str(settings.searchdb_working_dir) if settings.searchdb_working_dir else None,
        "local_cached_db_path": str(settings.local_db_path),
        "copy_policy": settings.copy_policy,
        "metadata_path": str(_metadata_path(settings.local_db_path)),
        "metadata": metadata,
    }
