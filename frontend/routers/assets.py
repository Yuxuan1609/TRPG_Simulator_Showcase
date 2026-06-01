"""frontend/routers/assets.py — Asset background serving API."""
from __future__ import annotations

import os
import random
from pathlib import Path
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from frontend._paths import PROJECT_ROOT, FRONTEND_DIR

router = APIRouter(prefix="/api/assets", tags=["assets"])

ASSETS_DIR = FRONTEND_DIR / "static" / "assets"

# Map page context to asset subfolder
CONTEXT_MAP = {
    "module-gen": "module-gen",
    "game": "game",
    "character": "character",
    "launcher": "module-gen",  # launcher shares with module-gen
    "editor": "game",  # editor shares with game
}


@router.get("/list")
async def list_assets(
    context: str = Query(default="game", description="Page context: module-gen, game, character, launcher, editor"),
):
    """Return list of image/video assets for the given page context."""
    folder = CONTEXT_MAP.get(context, "game")
    target_dir = ASSETS_DIR / folder
    if not target_dir.exists():
        return JSONResponse({"images": [], "videos": []})

    images = []
    videos = []
    for f in sorted(target_dir.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        rel_path = f"/static/assets/{folder}/{f.name}"
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            images.append({"url": rel_path, "name": f.name, "type": "image"})
        elif ext in (".mp4", ".mov", ".avi", ".webm"):
            videos.append({"url": rel_path, "name": f.name, "type": "video"})

    return {"images": images, "videos": videos, "context": context, "folder": folder}


@router.get("/random")
async def random_asset(
    context: str = Query(default="game"),
    type_filter: str = Query(default="", description="Filter by type: image, video, or empty for any"),
):
    """Return a single random asset for the given context."""
    folder = CONTEXT_MAP.get(context, "game")
    target_dir = ASSETS_DIR / folder
    if not target_dir.exists():
        return JSONResponse({"url": "", "type": "", "error": "No assets found"})

    candidates = []
    for f in target_dir.iterdir():
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        rel_path = f"/static/assets/{folder}/{f.name}"
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            if not type_filter or type_filter == "image":
                candidates.append({"url": rel_path, "type": "image", "name": f.name})
        elif ext in (".mp4", ".mov", ".avi", ".webm"):
            if not type_filter or type_filter == "video":
                candidates.append({"url": rel_path, "type": "video", "name": f.name})

    if not candidates:
        return JSONResponse({"url": "", "type": "", "error": "No matching assets"})

    asset = random.choice(candidates)
    return asset
