from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

import uvicorn

from searchviewer.app import create_app
from searchviewer.diagnostics import configure_logging, json_for_log, make_log_path
from searchviewer.distribution import default_settings_path, load_distribution_settings
from searchviewer.frontend import inspect_static_bundle, static_dir


LOGGER = logging.getLogger("searchviewer.launcher")


def _ensure_source_searchdb_path() -> None:
    if getattr(sys, "frozen", False):
        return
    searchdb_src = Path(__file__).resolve().parents[3] / "SearchDB" / "src"
    if searchdb_src.exists():
        searchdb_text = str(searchdb_src)
        if searchdb_text not in sys.path:
            sys.path.insert(0, searchdb_text)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _path_exists_quietly(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


class EmbeddedServer:
    def __init__(
        self,
        *,
        app_factory: Callable[[], Any],
        port: int,
        host: str = "127.0.0.1",
    ) -> None:
        self.app_factory = app_factory
        self.port = port
        self.host = host
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.stopped = False

    @property
    def url(self) -> str:
        return build_local_url(self.port)

    def start(self) -> None:
        config = uvicorn.Config(
            self.app_factory(),
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
            log_config=None,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="SearchViewerServer", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopped = True
        if self.server is not None:
            self.server.should_exit = True

    def wait_until_started(self, timeout_seconds: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.server is not None and self.server.started:
                return True
            time.sleep(0.05)
        return False


def start_server_and_open_browser(
    server: Any,
    *,
    open_browser: Callable[[str], Any] = webbrowser.open,
) -> bool:
    try:
        server.start()
    except Exception:
        LOGGER.exception("embedded_server_start_failed url=%s", getattr(server, "url", "<unknown>"))
        return False

    started = bool(server.wait_until_started())
    LOGGER.info("embedded_server_started=%s url=%s", started, server.url)
    if started:
        open_browser(server.url)
    else:
        LOGGER.error("embedded_server_start_timeout url=%s", server.url)
    return started


def smoke_check(settings_path: str | Path | None = None) -> dict[str, Any]:
    selected_settings_path = Path(settings_path) if settings_path is not None else default_settings_path()
    static_report = inspect_static_bundle(static_dir())
    payload: dict[str, Any] = {
        "ok": True,
        "settings": {
            "path": str(selected_settings_path.resolve()),
            "exists": selected_settings_path.exists(),
        },
        "static": static_report,
        "searchdb_importable": False,
    }

    try:
        _ensure_source_searchdb_path()
        import searchdb  # noqa: F401

        payload["searchdb_importable"] = True
    except ImportError as exc:
        payload["ok"] = False
        payload["searchdb_error"] = str(exc)

    if selected_settings_path.exists():
        try:
            settings = load_distribution_settings(selected_settings_path)
            shared_config_exists = _path_exists_quietly(settings.shared_config_path)
            shared_db_exists = _path_exists_quietly(settings.shared_db_path)
            payload["settings"].update(
                {
                    "valid": True,
                    "shared_config_path": str(settings.shared_config_path),
                    "shared_db_path": str(settings.shared_db_path),
                    "searchdb_working_dir": str(settings.searchdb_working_dir)
                    if settings.searchdb_working_dir
                    else None,
                    "local_cached_db_path": str(settings.local_db_path),
                    "shared_config_exists": shared_config_exists,
                    "shared_db_exists": shared_db_exists,
                }
            )
            if shared_config_exists and shared_db_exists:
                from searchviewer.backend import ViewerBackend

                backend = ViewerBackend(settings_path=selected_settings_path)
                status = backend.status()
                payload["backend"] = {
                    "connected": status["connection"]["mode"] != "disconnected",
                    "mode": status["connection"]["mode"],
                    "db_path": status["connection"]["db_path"],
                    "distribution_error": status["distribution"]["error"],
                }
                if not payload["backend"]["connected"]:
                    payload["ok"] = False
        except Exception as exc:  # smoke output should report all packaging problems.
            payload["ok"] = False
            payload["settings"].update({"valid": False, "error": str(exc)})
    else:
        payload["ok"] = False

    if not payload["static"]["ok"]:
        payload["ok"] = False
    LOGGER.info("smoke_check %s", json_for_log(payload))
    return payload


def _run_gui(
    settings_path: Path,
    *,
    log_dir: str | Path | None = None,
    log_path: str | Path | None = None,
) -> int:
    import tkinter as tk
    from tkinter import messagebox

    selected_log_path = Path(log_path).resolve() if log_path is not None else configure_logging(make_log_path(log_dir))
    port = find_free_port()
    url = build_local_url(port)
    static_report = inspect_static_bundle(static_dir())
    LOGGER.info(
        "launcher_start %s",
        json_for_log(
            {
                "sys_frozen": bool(getattr(sys, "frozen", False)),
                "sys_executable": sys.executable,
                "meipass": getattr(sys, "_MEIPASS", None),
                "cwd": str(Path.cwd()),
                "settings_path": str(settings_path),
                "settings_exists": settings_path.exists(),
                "static": static_report,
                "port": port,
                "url": url,
                "log_path": str(selected_log_path),
            }
        ),
    )
    app_factory = lambda: create_app(settings_path=settings_path)
    server = EmbeddedServer(app_factory=app_factory, port=port)
    started = start_server_and_open_browser(server)

    root = tk.Tk()
    root.title("SearchViewer")
    root.geometry("620x240")
    root.resizable(False, False)

    if not started:
        status_text = "SearchViewer の起動に失敗しました。ログを確認してください。"
    elif not settings_path.exists():
        status_text = "設定ファイルが見つかりません。画面で接続設定を確認してください。"
    else:
        status_text = "SearchViewer を起動しました。"
    status_var = tk.StringVar(value=status_text)
    url_var = tk.StringVar(value=url)
    settings_var = tk.StringVar(value=f"設定: {settings_path}")
    log_var = tk.StringVar(value=f"ログ: {selected_log_path}")

    def open_browser() -> None:
        if started:
            webbrowser.open(url)

    def stop_and_close() -> None:
        server.stop()
        root.destroy()

    def copy_url() -> None:
        root.clipboard_clear()
        root.clipboard_append(url)
        status_var.set("URLをクリップボードにコピーしました。")

    def copy_log_path() -> None:
        root.clipboard_clear()
        root.clipboard_append(str(selected_log_path))
        status_var.set("ログパスをクリップボードにコピーしました。")

    def open_log_folder() -> None:
        os.startfile(str(selected_log_path.parent))  # type: ignore[attr-defined]

    tk.Label(root, textvariable=status_var, anchor="w").pack(fill="x", padx=14, pady=(14, 4))
    tk.Label(root, textvariable=url_var, anchor="w", fg="#155f85").pack(fill="x", padx=14, pady=4)
    tk.Label(root, textvariable=settings_var, anchor="w").pack(fill="x", padx=14, pady=4)
    tk.Label(root, textvariable=log_var, anchor="w").pack(fill="x", padx=14, pady=4)

    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=14, pady=12)
    tk.Button(
        buttons,
        text="ブラウザを開く",
        command=open_browser,
        width=14,
        state=("normal" if started else "disabled"),
    ).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="URLをコピー", command=copy_url, width=12).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="ログフォルダ", command=open_log_folder, width=12).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="ログパス", command=copy_log_path, width=10).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="終了", command=stop_and_close, width=10).pack(side="right")

    def on_close() -> None:
        if messagebox.askokcancel("SearchViewer", "SearchViewerを終了しますか?"):
            stop_and_close()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    if server.thread is not None:
        server.thread.join(timeout=5)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="SearchViewer")
    parser.add_argument("--settings", default=None)
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--smoke-output", default=None)
    args = parser.parse_args(argv)

    settings_path = Path(args.settings).resolve() if args.settings else default_settings_path()
    log_path = configure_logging(make_log_path(args.log_dir))
    LOGGER.info(
        "main_start %s",
        json_for_log(
            {
                "smoke": bool(args.smoke),
                "settings_path": str(settings_path),
                "smoke_output": args.smoke_output,
                "log_path": str(log_path),
            }
        ),
    )
    if args.smoke:
        payload = smoke_check(settings_path=settings_path)
        payload["log"] = {"path": str(log_path)}
        if args.smoke_output:
            output_path = Path(args.smoke_output).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    return _run_gui(settings_path, log_dir=args.log_dir, log_path=log_path)


if __name__ == "__main__":
    raise SystemExit(main())
