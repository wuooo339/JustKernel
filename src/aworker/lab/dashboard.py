"""Serve a coherent dashboard version without stale external-browser scripts."""

import hashlib
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope


# ---- DashboardFiles ---------------------------------------------------------
class DashboardFiles(StaticFiles):
    # ---- construction and response freshness --------------------------------
    def __init__(self, directory: Path, *, demo_only: bool = False):
        super().__init__(directory=directory, html=True)
        self.web = directory.resolve()
        self.demo_only = demo_only

    async def get_response(self, path: str, scope: Scope) -> Response:
        # Always render the entry page: its own mtime does not reflect JS changes.
        if path in {".", "", "index.html"} and scope["method"] in {"GET", "HEAD"}:
            content = (self.web / "index.html").read_text(encoding="utf-8")
            if self.demo_only:
                content = content.replace(
                    "</head>", "<script>window.JUSTKERNEL_DEMO_ONLY=true;</script></head>"
                )

            def version(match: re.Match) -> str:
                asset = self.web / match[2]
                digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
                return f'{match[1]}="{match[2]}?v={digest}"'

            content = re.sub(r'(href|src)="([\w./-]+\.(?:css|js))"', version, content)
            response = HTMLResponse(content, headers={"Cache-Control": "no-store"})
            if scope["method"] == "HEAD":
                response.body = b""
            return response
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


# ---- create_demo_app --------------------------------------------------------
def create_demo_app() -> FastAPI:
    """Serve the same frontend without creating workspaces or reading model credentials."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/lab/health")
    async def health():
        return {"ok": True, "demo_only": True, "model_calls": False, "npu_configured": False}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def unavailable(path: str):
        return JSONResponse(
            {"detail": "当前为轻量预演。真实配置与优化请使用 justkernel serve。"}, status_code=409
        )

    web = Path(__file__).parent / "resources/web"
    app.mount("/", DashboardFiles(web, demo_only=True))
    return app


# ---- serve_demo -------------------------------------------------------------
def serve_demo(host: str, port: int, open_browser: bool = False):
    import threading
    import webbrowser

    import uvicorn

    print(f"JustKernel demo: http://{host}:{port}/ (simulated data; no model or device calls)")
    if open_browser:
        launch = threading.Timer(1, webbrowser.open, args=(f"http://{host}:{port}/",))
        launch.daemon = True
        launch.start()
    uvicorn.run(create_demo_app(), host=host, port=port, access_log=False)
