"""Serve the buildless dashboard beside the API; no extra process or CORS needed."""
import mimetypes
from pathlib import Path

from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def install_frontend(app):
    mimetypes.add_type("text/javascript", ".js")
    if (FRONTEND / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def dashboard_page():
        if (FRONTEND / "index.html").is_file():
            return FileResponse(FRONTEND / "index.html", media_type="text/html")
        return RedirectResponse("/docs")

    @app.middleware("http")
    async def frontend_headers(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/assets/"):
            response.headers["Content-Security-Policy"] = CSP
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["X-Frame-Options"] = "DENY"
        if path == "/" or path.startswith("/assets/") or path.startswith("/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response
