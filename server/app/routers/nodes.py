"""Nodes: create (branch), retry, star/archive/note, cancel, chains, import."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..access import chain_access, node_access, project_access
from ..auth import Identity, current_identity
from ..db import session_scope
from ..models import AssetKind, Chain, Node, NodeStatus, OpType
from ..pipeline.engine import engine
from ..pipeline.tripo_options import OP_SPECS

router = APIRouter(prefix="/api", tags=["nodes"])


class NodeIn(BaseModel):
    op: OpType
    parent_id: Optional[str] = None
    options: dict[str, Any] = {}
    n: int = 1


@router.post("/projects/{project_id}/nodes")
async def create_nodes(project_id: str, body: NodeIn,
                       ident: Identity = Depends(current_identity)) -> list[Node]:
    """Branch: create n sibling nodes under parent_id and start them."""
    await project_access(project_id, ident, write=True)
    if body.parent_id:
        try:
            parent = await engine.get_node(body.parent_id)
        except KeyError:
            raise HTTPException(404, "parent node not found")
        if parent.project_id != project_id:
            raise HTTPException(400, "parent belongs to a different project")
    n = max(1, min(16, body.n))
    return await engine.create_nodes(project_id, body.parent_id, body.op, body.options, n=n)


@router.get("/nodes/{node_id}")
async def get_node(node_id: str,
                   ident: Identity = Depends(current_identity)) -> dict:
    node = await node_access(node_id, ident)
    assets = await engine.node_assets(node_id)
    return {**node.model_dump(), "assets": [a.model_dump() for a in assets]}


@router.post("/nodes/{node_id}/retry")
async def retry_node(node_id: str, options: dict[str, Any] | None = None,
                     n: int = 1,
                     ident: Identity = Depends(current_identity)) -> list[Node]:
    """New sibling(s) under the same parent with (optionally tweaked) options."""
    node = await node_access(node_id, ident, write=True)
    merged = {**node.options, **(options or {})}
    merged.pop("rig_submitted", None)
    merged.pop("rig_type_resolved", None)
    return await engine.create_nodes(node.project_id, node.parent_id, node.op_type,
                                     merged, n=max(1, min(16, n)))


class NodePatch(BaseModel):
    starred: Optional[bool] = None
    archived: Optional[bool] = None
    note: Optional[str] = None


@router.patch("/nodes/{node_id}")
async def patch_node(node_id: str, body: NodePatch,
                     ident: Identity = Depends(current_identity)) -> Node:
    await node_access(node_id, ident, write=True)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return await engine.update_node(node_id, **fields)
    except AttributeError:
        raise HTTPException(404, "node not found")


@router.post("/nodes/{node_id}/cancel")
async def cancel_node(node_id: str,
                      ident: Identity = Depends(current_identity)) -> dict:
    await node_access(node_id, ident, write=True)
    await engine.cancel_node(node_id)
    return {"ok": True}


class ChainSpec(BaseModel):
    op: OpType
    options: dict[str, Any] = {}
    n: int = 1
    select: str = "first"      # first | starred


class ChainIn(BaseModel):
    specs: list[ChainSpec]


@router.post("/nodes/{node_id}/chain")
async def start_chain(node_id: str, body: ChainIn,
                      ident: Identity = Depends(current_identity)) -> Chain:
    """Run several steps in one call, branching down from this node."""
    node = await node_access(node_id, ident, write=True)
    if not body.specs:
        raise HTTPException(400, "empty chain")
    return await engine.start_chain(node.project_id, node.id,
                                    [s.model_dump() for s in body.specs])


@router.get("/chains/{chain_id}")
async def get_chain(chain_id: str,
                    ident: Identity = Depends(current_identity)) -> Chain:
    return await chain_access(chain_id, ident)


@router.post("/chains/{chain_id}/cancel")
async def cancel_chain(chain_id: str,
                       ident: Identity = Depends(current_identity)) -> dict:
    await chain_access(chain_id, ident, write=True)
    await engine.cancel_chain(chain_id)
    return {"ok": True}


@router.post("/projects/{project_id}/import")
async def import_model(project_id: str, file: UploadFile = File(...),
                       ident: Identity = Depends(current_identity)) -> Node:
    """Bring an external model (glb/fbx/obj/...) into the tree as a root node."""
    await project_access(project_id, ident, write=True)
    nodes = await engine.create_nodes(project_id, None, OpType.import_model, {},
                                      autostart=False)
    node = nodes[0]
    ext = (file.filename or "model.glb").rsplit(".", 1)[-1].lower()
    dest = engine.node_dir(project_id, node.id) / f"model.{ext}"
    dest.write_bytes(await file.read())
    meta = {"format": ext, "filename": file.filename}
    if ext in ("glb", "gltf"):
        from ..pipeline.meshinfo import glb_bounds
        b = glb_bounds(dest)
        if b:
            meta["bounds"] = b
    await engine.add_asset(node, AssetKind.model, dest, meta)
    await engine.update_node(node.id, status=NodeStatus.completed, progress=100,
                             provider="local")
    return await engine.get_node(node.id)


@router.post("/nodes/{node_id}/refs")
async def upload_node_ref(node_id: str, file: UploadFile = File(...),
                          ident: Identity = Depends(current_identity)) -> dict:
    """Add a reference image to a ref_set node."""
    node = await node_access(node_id, ident, write=True)
    if node.op_type != OpType.ref_set:
        raise HTTPException(400, "refs can only be added to ref_set nodes")
    dest = engine.node_dir(node.project_id, node.id) / (file.filename or "ref.png")
    i = 1
    while dest.exists():
        dest = dest.with_name(f"{dest.stem}_{i}{dest.suffix}")
        i += 1
    dest.write_bytes(await file.read())
    asset = await engine.add_asset(node, AssetKind.ref, dest, {"filename": file.filename})
    return asset.model_dump()


@router.post("/nodes/{node_id}/duplicate")
async def duplicate_node(node_id: str,
                         ident: Identity = Depends(current_identity)) -> Node:
    """Duplicate a ref_set (new sibling with copies of the refs) — branch a
    different reference set from an existing one."""
    import shutil
    node = await node_access(node_id, ident, write=True)
    if node.op_type != OpType.ref_set:
        raise HTTPException(400, "only ref_set nodes can be duplicated")
    twins = await engine.create_nodes(node.project_id, node.parent_id, OpType.ref_set,
                                      dict(node.options), autostart=False)
    twin = twins[0]
    for a in await engine.node_assets(node.id, AssetKind.ref):
        src = engine.abs(a.path)
        dest = engine.node_dir(twin.project_id, twin.id) / src.name
        shutil.copy(src, dest)
        await engine.add_asset(twin, AssetKind.ref, dest, dict(a.meta))
    await engine.update_node(twin.id, status=NodeStatus.completed, progress=100,
                             provider="local", note=f"duplicated from {node.id}")
    return await engine.get_node(twin.id)


class EidoverseIn(BaseModel):
    as_avatar: bool = False
    name: Optional[str] = None       # avatar name (sanitized server-side by eidoverse)
    height: Optional[float] = None   # avatar height in meters (glb2vrm --height)
    target: str = "eidoverse"        # push target: "eidoverse" (prod) | "eidoverse2" (staging)


@router.get("/eidoverse/targets")
async def eidoverse_targets(ident: Identity = Depends(current_identity)) -> dict:
    """Configured world push targets — drives the UI target picker (a lone
    'eidoverse' renders no picker at all)."""
    from ..services import eidoverse
    return {"targets": list(eidoverse.targets().keys())}


@router.post("/nodes/{node_id}/send-to-eidoverse")
async def send_to_eidoverse(node_id: str, body: EidoverseIn,
                            ident: Identity = Depends(current_identity)) -> dict:
    """Push this node's GLB into eidoverse-worlds — as a world object, or
    (for rigged characters) converted to a VRM 1.0 avatar. `target` picks the
    world: "eidoverse" (default, prod) or "eidoverse2" (staging, when configured)."""
    from ..services import eidoverse
    if body.target not in eidoverse.targets():
        raise HTTPException(400, f"unknown target '{body.target}' — configured: "
                                 f"{', '.join(eidoverse.targets())}")
    node = await node_access(node_id, ident, write=True)
    models = await engine.node_assets(node_id, AssetKind.model)
    glbs = [a for a in models if (a.meta.get("format") or "glb") in ("glb", "gltf", "vrm")]
    if not glbs:
        raise HTTPException(400, "node has no GLB model output (eidoverse needs .glb; "
                                 "convert FBX nodes to GLTF first)")
    path = engine.abs(glbs[0].path)
    try:
        if body.as_avatar:
            name = body.name or f"orrery-{node.project_id[:6]}-{node.id[:6]}"
            result = await eidoverse.send_avatar(path, name, body.height, by=ident.name,
                                                 target=body.target)
        else:
            project = await engine.get_project(node.project_id)
            name = body.name or f"{project.name} {node.id[:6]}"
            result = await eidoverse.send_object(path, name=name, by=ident.name,
                                                 target=body.target)
    except eidoverse.EidoverseTooLarge as e:
        raise HTTPException(413, str(e))          # local pre-flight, not a far-end failure
    except eidoverse.EidoverseError as e:
        raise HTTPException(502, str(e))
    note = (node.note + " | " if node.note else "") + f"{body.target}: {result.get('path')}"
    await engine.update_node(node_id, note=note[:500])
    return {"ok": True, **result, "as_avatar": body.as_avatar, "target": body.target}


@router.get("/ops")
async def op_catalog(ident: Identity = Depends(current_identity)) -> dict:
    """Option specs for every op — drives the UI forms and agent discovery."""
    return OP_SPECS
