# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).resolve().parent
SEARCHVIEWER_SRC = ROOT / "src"
SEARCHDB_SRC = Path(os.environ.get("SEARCHVIEWER_SEARCHDB_SRC", ROOT.parent / "SearchDB" / "src")).resolve()
SEARCHDB_PACKAGE = SEARCHDB_SRC / "searchdb"
FRONTEND_DIST = ROOT / "frontend" / "dist"

if not SEARCHDB_PACKAGE.exists():
    raise SystemExit(f"SearchDB package source not found: {SEARCHDB_PACKAGE}")
if not FRONTEND_DIST.exists():
    raise SystemExit(f"frontend dist not found: {FRONTEND_DIST}; run npm --prefix frontend run build first")

for path in (SEARCHVIEWER_SRC, SEARCHDB_SRC):
    path_text = str(path)
    if path.exists() and path_text not in sys.path:
        sys.path.insert(0, path_text)

datas = []
if FRONTEND_DIST.exists():
    datas.append((str(FRONTEND_DIST), "searchviewer_static"))

searchdb_sql = SEARCHDB_PACKAGE / "sql"
if searchdb_sql.exists():
    datas.append((str(searchdb_sql), "searchdb/sql"))

hiddenimports = collect_submodules("searchviewer")
hiddenimports += [
    "searchdb",
    "searchdb.access_guard",
    "searchdb.config",
    "searchdb.db",
    "searchdb.query",
    "searchdb.ranking",
    "searchdb.readiness",
    "searchdb.schema",
    "searchdb.targets",
]

a = Analysis(
    [str(ROOT / "packaging" / "searchviewer_launcher.py")],
    pathex=[str(SEARCHVIEWER_SRC), str(SEARCHDB_SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SearchViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
