from __future__ import annotations

import sys
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


class _StaticAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        tag_name = tag.lower()
        if tag_name == "script" and attr_map.get("src"):
            self._append("script", attr_map["src"])
            return
        if tag_name != "link" or not attr_map.get("href"):
            return
        rel_values = {item.strip().lower() for item in attr_map.get("rel", "").split()}
        if "stylesheet" in rel_values:
            self._append("stylesheet", attr_map["href"])

    def _append(self, kind: str, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            return
        self.assets.append({"kind": kind, "path": unquote(parsed.path or url)})


def static_dir() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root) / "searchviewer_static"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def inspect_static_bundle(root: str | Path | None = None) -> dict[str, Any]:
    selected_root = Path(root) if root is not None else static_dir()
    selected_root = selected_root.resolve()
    index_path = selected_root / "index.html"
    report: dict[str, Any] = {
        "path": str(selected_root),
        "exists": selected_root.exists(),
        "index_path": str(index_path),
        "index_exists": index_path.exists(),
        "referenced_assets": [],
        "missing_assets": [],
        "errors": [],
        "ok": False,
    }

    if not selected_root.exists():
        report["errors"].append(f"static directory not found: {selected_root}")
        return report
    if not index_path.exists():
        report["errors"].append(f"index.html not found: {index_path}")
        return report

    try:
        html = index_path.read_text(encoding="utf-8")
    except OSError as exc:
        report["errors"].append(f"index.html is not readable: {exc}")
        return report

    parser = _StaticAssetParser()
    parser.feed(html)
    referenced_assets: list[dict[str, Any]] = []
    missing_assets: list[str] = []
    script_count = 0
    for asset in parser.assets:
        asset_path = asset["path"]
        if asset["kind"] == "script":
            script_count += 1
        relative_path = asset_path.lstrip("/")
        local_path = (selected_root / relative_path).resolve()
        try:
            local_path.relative_to(selected_root)
        except ValueError:
            exists = False
        else:
            exists = local_path.exists()
        referenced_assets.append(
            {
                "kind": asset["kind"],
                "path": asset_path,
                "file_path": str(local_path),
                "exists": exists,
            }
        )
        if not exists:
            missing_assets.append(asset_path)

    if script_count == 0:
        report["errors"].append("index.html does not reference a script asset")

    report["referenced_assets"] = referenced_assets
    report["missing_assets"] = missing_assets
    report["ok"] = bool(
        report["exists"] and report["index_exists"] and not report["errors"] and not missing_assets
    )
    return report


def static_error_html(report: dict[str, Any]) -> str:
    missing_assets = report.get("missing_assets") or []
    errors = report.get("errors") or []
    details = [*errors, *[f"missing asset: {asset}" for asset in missing_assets]]
    if not details:
        details = ["static bundle validation failed"]
    detail_items = "\n".join(f"<li>{escape(str(item))}</li>" for item in details)
    root = escape(str(report.get("path") or ""))
    index = escape(str(report.get("index_path") or ""))
    return f"""<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>SearchViewer startup diagnostics</title>
    <style>
      body {{ font-family: Segoe UI, sans-serif; margin: 32px; color: #1b2733; }}
      code {{ background: #edf2f7; padding: 2px 5px; border-radius: 4px; }}
      li {{ margin: 6px 0; }}
    </style>
  </head>
  <body>
    <h1>SearchViewer static bundle is incomplete</h1>
    <p>The local server is running, but the packaged frontend files are incomplete.</p>
    <p>Static directory: <code>{root}</code></p>
    <p>Index file: <code>{index}</code></p>
    <ul>{detail_items}</ul>
  </body>
</html>"""
