"""Backend handoff: expose API docs until the frontend stage is applied."""
from fastapi.responses import RedirectResponse


def install_frontend(app):
    @app.get("/", include_in_schema=False)
    def api_home():
        return RedirectResponse("/docs")
