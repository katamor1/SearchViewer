from __future__ import annotations

import json
import logging
import time
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.datastructures import Headers
from starlette.responses import FileResponse
from starlette.staticfiles import NotModifiedResponse

from searchviewer.backend import ViewerBackend
from searchviewer.diagnostics import (
    CLIENT_LOG_MAX_BYTES,
    json_for_log,
    sanitize_client_log_payload,
)
from searchviewer.frontend import inspect_static_bundle, static_dir, static_error_html


LOGGER = logging.getLogger("searchviewer.app")
CLIENT_LOGGER = logging.getLogger("searchviewer.client")
LOCAL_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
STATIC_MEDIA_TYPES = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
}


class SearchViewerStaticFiles(StaticFiles):
    def file_response(
        self,
        full_path,
        stat_result,
        scope,
        status_code: int = 200,
    ) -> Response:
        request_headers = Headers(scope=scope)
        media_type = STATIC_MEDIA_TYPES.get(Path(full_path).suffix.lower())
        response = FileResponse(
            full_path,
            status_code=status_code,
            stat_result=stat_result,
            media_type=media_type,
        )
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response


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

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            LOGGER.exception(
                "request_failed method=%s path=%s duration_ms=%.1f",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        LOGGER.info(
            "request method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return viewer.status()

    @app.post("/api/client-log", status_code=204)
    async def client_log(request: Request) -> Response:
        host = request.client.host if request.client else ""
        if host not in LOCAL_CLIENT_HOSTS:
            raise HTTPException(status_code=403, detail="client logging is only available locally")

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > CLIENT_LOG_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="client log payload is too large")
            except ValueError:
                raise HTTPException(status_code=400, detail="invalid content-length") from None

        body = await request.body()
        if len(body) > CLIENT_LOG_MAX_BYTES:
            raise HTTPException(status_code=413, detail="client log payload is too large")

        payload: Any
        content_type = request.headers.get("content-type", "")
        text = body.decode("utf-8", errors="replace")
        if "application/json" in content_type:
            try:
                payload = json.loads(text or "{}")
            except JSONDecodeError:
                payload = {"type": "invalid_json"}
        else:
            try:
                payload = json.loads(text)
            except JSONDecodeError:
                payload = {"type": "client_text", "message": text[:500]}

        CLIENT_LOGGER.info("client_event %s", json_for_log(sanitize_client_log_payload(payload)))
        return Response(status_code=204)

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
    static_report = inspect_static_bundle(dist_dir)
    app.state.static_report = static_report
    LOGGER.info("static_bundle %s", json_for_log(static_report))
    if static_report["ok"]:
        app.mount("/", SearchViewerStaticFiles(directory=dist_dir, html=True), name="static")
    else:
        LOGGER.error("static_bundle_incomplete %s", json_for_log(static_report))

        @app.get("/{full_path:path}", include_in_schema=False)
        def static_unavailable(full_path: str) -> HTMLResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            return HTMLResponse(static_error_html(static_report), status_code=503)

    return app


app = create_app()
