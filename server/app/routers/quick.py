"""One-call mode: prompt (+ optional refs) -> finished textured 3D model."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..access import project_access
from ..auth import Identity, current_identity
from ..db import session_scope
from ..models import Chain, ChainStatus, NodeStatus, OpType, Project
from ..pipeline.engine import engine

router = APIRouter(prefix="/api", tags=["quick"])


class QuickIn(BaseModel):
    prompt: str
    project_id: Optional[str] = None       # reuse a project (and its refs); else create one
    name: Optional[str] = None
    n_images: int = 1
    n_meshes: int = 1
    image_options: dict[str, Any] = {}     # resolution/quality/... overrides
    mesh_options: dict[str, Any] = {}      # tripo overrides (model, texture_quality, ...)
    approve_images: bool = False           # pause after image gen until a candidate is starred


@router.post("/quick")
async def quick(body: QuickIn, wait: bool = False, timeout_s: int = 1800,
                ident: Identity = Depends(current_identity)) -> dict:
    if body.project_id:
        project = await project_access(body.project_id, ident, write=True)
    else:
        project = Project(name=body.name or body.prompt[:40], prompt=body.prompt,
                          owner_sub=ident.sub, owner_name=ident.name)
        async with session_scope() as s:
            s.add(project)
            await s.commit()

    image_opts = {"prompt": body.prompt, **body.image_options}
    mesh_opts = {"texture": True, "pbr": True, **body.mesh_options}

    # anchor on the project's newest ref_set (if any) so its references are used
    anchor = None
    async with session_scope() as s:
        from sqlmodel import select
        from ..models import Node, OpType as OT
        q = (select(Node).where(Node.project_id == project.id,
                                Node.op_type == OT.ref_set,
                                Node.archived == False)  # noqa: E712
             .order_by(Node.created_at.desc()))
        ref_sets = list((await s.execute(q)).scalars().all())
        if ref_sets:
            anchor = ref_sets[0].id

    # the whole pipeline is one chain; select=first tolerates sibling failures,
    # select=starred (approve_images) waits for a human/agent to star a candidate
    chain = await engine.start_chain(project.id, anchor, [
        {"op": "image_gen", "options": image_opts,
         "n": max(1, min(8, body.n_images)),
         "select": "starred" if body.approve_images else "first"},
        {"op": "split", "options": {}, "n": 1, "select": "first"},
        {"op": "mesh_gen", "options": mesh_opts,
         "n": max(1, min(6, body.n_meshes)), "select": "first"},
    ])
    result = {"project_id": project.id, "chain_id": chain.id}
    if not wait:
        return result

    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        async with session_scope() as s:
            c = await s.get(Chain, chain.id)
        if c.status == ChainStatus.completed:
            final = await engine.get_node(c.anchor_node_id)
            assets = await engine.node_assets(final.id)
            return {**result, "status": "completed", "final_node_id": final.id,
                    "assets": [a.model_dump() for a in assets],
                    "credits": final.credits}
        if c.status in (ChainStatus.failed, ChainStatus.cancelled):
            return {**result, "status": c.status, "error": c.error}
        await asyncio.sleep(2.0)
    return {**result, "status": "timeout"}
