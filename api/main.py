"""Application entry point.

Serves the JSON API under /api and, in a built image, the compiled front end
for everything else. One origin for both is what lets the session cookie be a
plain `SameSite=Lax` cookie with no CORS configuration to get wrong.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.config import settings
from api.routers import auth, projects, variables

# Written here by the Dockerfile's front-end build stage. Absent in local
# API-only development, where Vite serves the front end on its own port and
# proxies /api across — see web/vite.config.ts.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(
    title="Machining model platform",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(auth.router)
app.include_router(variables.router)
app.include_router(projects.router)


@app.get("/api/health")
def health():
    """Enough to tell a broken deployment from a broken database."""
    from sqlalchemy import text

    from api.db import engine

    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        database = "ok"
    except Exception as error:  # noqa: BLE001 - reported, not raised
        database = f"error: {type(error).__name__}"

    return {
        "ok": database == "ok",
        "environment": settings.environment,
        "database": database,
        "front_end_built": WEB_DIST.exists(),
    }


@app.exception_handler(404)
async def spa_fallback(request: Request, exc: HTTPException):
    """Hand unknown non-API paths to the front end's client-side router.

    A deep link like /projects/titanium-residual-stress is a React route, not a
    file on disk. Anything under /api keeps its honest 404 — silently returning
    an HTML page to a mistyped API call makes for a baffling debugging session.
    """
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": exc.detail}, status_code=404)
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {
            "detail": "Front end not built. Run `docker compose up --build`, or "
            "`npm run dev` in web/ for local development."
        },
        status_code=404,
    )


# Mounted last so it cannot shadow /api/*.
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
