from __future__ import annotations

import sys
from pathlib import Path


def static_dir() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root) / "searchviewer_static"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"
