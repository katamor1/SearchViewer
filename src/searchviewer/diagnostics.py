from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any


CLIENT_LOG_MAX_BYTES = 4096
_HANDLER_MARKER = "_searchviewer_diagnostic_handler"
_CLIENT_LOG_FIELDS = {
    "type",
    "message",
    "source",
    "filename",
    "lineno",
    "colno",
    "tagName",
    "url",
    "href",
    "src",
    "asset",
    "userAgent",
}


def default_log_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SearchViewer" / "logs"
    return Path.home() / "AppData" / "Local" / "SearchViewer" / "logs"


def make_log_path(log_dir: str | Path | None = None) -> Path:
    selected_log_dir = Path(log_dir).expanduser() if log_dir is not None else default_log_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return selected_log_dir.resolve() / f"SearchViewer-{timestamp}.log"


def configure_logging(log_path: str | Path) -> Path:
    resolved = Path(log_path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root_logger.removeHandler(handler)
            handler.close()

    handler = logging.FileHandler(resolved, encoding="utf-8")
    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root_logger.addHandler(handler)
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)

    for logger_name in ("searchviewer", "uvicorn", "uvicorn.error"):
        logging.getLogger(logger_name).setLevel(logging.INFO)
    return resolved


def sanitize_client_log_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"type": "non_object_payload"}

    sanitized: dict[str, Any] = {}
    for key in sorted(_CLIENT_LOG_FIELDS):
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            continue
        if isinstance(value, bool | int | float):
            sanitized[key] = value
        else:
            sanitized[key] = str(value)[:500]
    if "type" not in sanitized:
        sanitized["type"] = "client_event"
    return sanitized


def json_for_log(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
