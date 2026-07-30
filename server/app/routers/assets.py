"""Serve archived asset files (images/models) to the UI and agents."""
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..access import asset_access
from ..auth import Identity, current_identity
from ..db import session_scope
from ..models import Asset, AssetKind
from ..pipeline.engine import engine

router = APIRouter(prefix="/api/assets", tags=["assets"])

mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")


@router.get("/{asset_id}")
async def get_asset_meta(asset_id: str,
                         ident: Identity = Depends(current_identity)) -> Asset:
    return await asset_access(asset_id, ident)


@router.delete("/{asset_id}")
async def delete_asset(asset_id: str,
                       ident: Identity = Depends(current_identity)) -> dict:
    """Delete an asset. Only reference images are deletable — node outputs are
    part of the append-only tree (archive the node instead)."""
    await asset_access(asset_id, ident, write=True)
    async with session_scope() as s:
        asset = await s.get(Asset, asset_id)
        if asset.kind != AssetKind.ref:
            raise HTTPException(400, "only reference images can be deleted; archive the node instead")
        await s.delete(asset)
        await s.commit()
    path = engine.abs(asset.path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


@router.get("/{asset_id}/file")
async def get_asset_file(asset_id: str,
                         ident: Identity = Depends(current_identity)):
    asset = await asset_access(asset_id, ident)
    path = engine.abs(asset.path)
    if not path.exists():
        raise HTTPException(410, "file missing on disk")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)
