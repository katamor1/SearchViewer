from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from searchviewer.backend import ViewerBackend
from searchviewer.frontend import static_dir


class ConnectRequest(BaseModel):
    config_path: str | None = None
    db_path: str | None = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    query_type: str = "spec_question"
    include_path: str | None = None
    exclude_path: str | None = None
    since: str | None = None


def create_app(
    backend: ViewerBackend | None = None,
    *,
    settings_path: str | Path | None = None,
) -> FastAPI:
    viewer = backend or ViewerBackend(settings_path=settings_path)
    app = FastAPI(title="SearchViewer", version="0.1.0")
    app.state.viewer_backend = viewer
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return viewer.status()

    @app.post("/api/connect")
    def connect(request: ConnectRequest) -> dict[str, Any]:
        try:
            return viewer.connect(request.model_dump())
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/search")
    def search(request: SearchRequest) -> dict[str, Any]:
        try:
            return viewer.search(request.model_dump())
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs")
    def runs(limit: int = 20) -> list[dict[str, Any]]:
        try:
            return viewer.recent_runs(limit=limit)
        except RuntimeError:
            return []

    @app.get("/api/runs/{run_id}")
    def run(run_id: int) -> dict[str, Any]:
        try:
            return viewer.run_payload(run_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/chunks/{chunk_id}")
    def chunk(chunk_id: int) -> dict[str, Any]:
        try:
            return viewer.chunk_detail(chunk_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/documents/{document_id}/open")
    def open_document(document_id: int) -> dict[str, Any]:
        try:
            return viewer.open_document(document_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    dist_dir = static_dir()
    if dist_dir.exists():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static")
    return app


app = create_app()
