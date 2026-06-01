"""frontend/routers/files.py — File browser API for navigating project directories."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from frontend._paths import PROJECT_ROOT, FRONTEND_DIR

router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_EXTENSIONS = {".json", ".docx", ".txt", ".pdf", ".md"}

# ── Jinja2 (reuse server's template engine path) ──
from fastapi.templating import Jinja2Templates
TEMPLATES_DIR = FRONTEND_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _safe_dir(directory: str) -> Path:
    raw = (PROJECT_ROOT / directory).resolve()
    if not str(raw).startswith(str(PROJECT_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not raw.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {directory}")
    return raw


@router.get("")
async def list_files(
    request: Request,
    dir: str = Query(default="data"),
    format: str = Query(default="html"),
    target_input: str = Query(default=""),
):
    base = _safe_dir(dir)
    items = list(base.iterdir())
    dirs = sorted(
        [{"name": d.name, "path": d.relative_to(PROJECT_ROOT).as_posix(), "ext": d.suffix}
         for d in items if d.is_dir() and not d.name.startswith(".")],
        key=lambda x: x["name"],
    )
    files = sorted(
        [{"name": f.name, "path": f.relative_to(PROJECT_ROOT).as_posix(), "ext": f.suffix}
         for f in items if f.is_file() and f.suffix in ALLOWED_EXTENSIONS],
        key=lambda x: x["name"],
    )
    parent = base.parent.relative_to(PROJECT_ROOT).as_posix() if base != PROJECT_ROOT else None
    current = base.relative_to(PROJECT_ROOT).as_posix()

    if format == "json":
        return {"dirs": dirs, "files": files, "parent": parent, "current": current}

    return templates.TemplateResponse(request, "partials/file-listing.html", {
        "dirs": dirs,
        "files": files,
        "parent": parent,
        "current": current,
        "target_input": target_input,
    })
