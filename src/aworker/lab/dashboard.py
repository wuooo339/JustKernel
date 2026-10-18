"""Serve a coherent dashboard version without stale external-browser scripts."""

import hashlib
import re
from pathlib import Path

from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope


# ---- DashboardFiles ---------------------------------------------------------
class DashboardFiles(StaticFiles):
    # ---- construction and response freshness --------------------------------
    def __init__(self, directory: Path):
        super().__init__(directory=directory, html=True)
        self.web = directory.resolve()

    async def get_response(self, path: str, scope: Scope) -> Response:
        # Always render the entry page: its own mtime does not reflect JS changes.
        if path in {".", "", "index.html"} and scope["method"] in {"GET", "HEAD"}:
            content = (self.web / "index.html").read_text(encoding="utf-8")

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
