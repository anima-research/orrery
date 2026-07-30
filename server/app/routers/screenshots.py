"""Headless turntable screenshots of a node's model — for agents (and thumbnails).

Implementation lands in services/renderer.py (Playwright + three.js).
Until then this router returns 501 for non-cached requests.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..access import node_access
from ..auth import Identity, current_identity
from ..models import AssetKind
from ..pipeline.engine import engine
from ..services import renderer

router = APIRouter(prefix="/api/nodes", tags=["screenshots"])


@router.get("/{node_id}/screenshots")
async def screenshots(node_id: str, count: int = 8, size: int = 1024,
                      elevation: float = 20.0, refresh: bool = False,
                      ident: Identity = Depends(current_identity)) -> dict:
    """Render (or reuse cached) turntable screenshots. Returns URLs to PNG files."""
    node = await node_access(node_id, ident)
    models = await engine.node_assets(node_id, AssetKind.model)
    if not models:
        raise HTTPException(400, "node has no model output")
    count = max(1, min(24, count))
    size = max(128, min(2048, size))
    try:
        shots = await renderer.turntable(engine.abs(models[0].path),
                                         engine.node_dir(node.project_id, node.id) / "screenshots",
                                         count=count, size=size, elevation=elevation,
                                         refresh=refresh)
    except renderer.RendererUnavailable as e:
        raise HTTPException(501, f"renderer unavailable: {e}")
    return {
        "node_id": node_id,
        "screenshots": [f"/api/nodes/{node_id}/screenshots/{p.name}" for p in shots],
    }


@router.get("/{node_id}/screenshots/{filename}")
async def screenshot_file(node_id: str, filename: str,
                          ident: Identity = Depends(current_identity)):
    node = await node_access(node_id, ident)
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "bad filename")
    path = engine.node_dir(node.project_id, node.id) / "screenshots" / filename
    if not path.exists():
        raise HTTPException(404, "screenshot not found")
    return FileResponse(path, media_type="image/png")
