"""Serve the built dashboard (frontend/dist) next to the API (D15).

Page routes and API paths overlap (/runs/:id, /connectors/:id), so a GET whose Accept header
asks for HTML gets the app's index.html, and everything else reaches the API unchanged. curl,
CI and fetch() calls (Accept: application/json or */*) keep getting JSON.

  /classic   the V1 status page, kept until the new dashboard reaches parity
  /assets/*  hashed build assets (cached hard)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist"
CLASSIC = ROOT / "frontend" / "classic.html"
API_DOCS = ("/docs", "/redoc", "/openapi.json")


def wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return request.method == "GET" and "text/html" in accept


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def spa_fallback(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        index = DIST / "index.html"
        if wants_html(request) and index.is_file() and not path.startswith(API_DOCS) and path != "/classic":
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return await call_next(request)

    app.mount("/assets", StaticFiles(directory=DIST / "assets", check_dir=False), name="assets")

    @app.get("/classic", include_in_schema=False)
    def classic() -> FileResponse:
        return FileResponse(CLASSIC)

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        built = DIST / "index.html"
        return FileResponse(built if built.is_file() else CLASSIC, headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> Response:
        icon = DIST / "favicon.svg"
        return FileResponse(icon, media_type="image/svg+xml") if icon.is_file() else Response(status_code=404)
