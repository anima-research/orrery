"""Projects: CRUD-lite, reference uploads, tree reads."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import select

from ..access import can_read, project_access
from ..auth import Identity, current_identity
from ..db import session_scope
from ..models import Asset, AssetKind, Chain, Node, Project
from ..pipeline.engine import engine

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str
    prompt: str = ""


@router.post("")
async def create_project(body: ProjectIn,
                         ident: Identity = Depends(current_identity)) -> Project:
    project = Project(name=body.name, prompt=body.prompt,
                      owner_sub=ident.sub, owner_name=ident.name)
    async with session_scope() as s:
        s.add(project)
        await s.commit()
    return project


@router.get("")
async def list_projects(ident: Identity = Depends(current_identity)) -> list[dict]:
    async with session_scope() as s:
        projects = list((await s.execute(select(Project).order_by(Project.created_at.desc()))).scalars())
        projects = [p for p in projects if can_read(p, ident)]
        out = []
        for p in projects:
            nodes = list((await s.execute(select(Node).where(Node.project_id == p.id))).scalars())
            out.append({
                **p.model_dump(),
                "node_count": len(nodes),
                "cost_usd": round(sum(n.cost_usd for n in nodes), 3),
                "credits": sum(n.credits for n in nodes),
            })
        return out


@router.get("/{project_id}")
async def get_project(project_id: str,
                      ident: Identity = Depends(current_identity)) -> Project:
    return await project_access(project_id, ident)


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    shared: Optional[bool] = None


@router.patch("/{project_id}")
async def patch_project(project_id: str, body: ProjectPatch,
                        ident: Identity = Depends(current_identity)) -> Project:
    await project_access(project_id, ident, write=True)
    async with session_scope() as s:
        p = await s.get(Project, project_id)
        if body.name is not None:
            p.name = body.name
        if body.prompt is not None:
            p.prompt = body.prompt
        if body.shared is not None:
            p.shared = body.shared
        s.add(p)
        await s.commit()
        return p


@router.post("/{project_id}/refs")
async def upload_ref(project_id: str, file: UploadFile = File(...),
                     ident: Identity = Depends(current_identity)) -> Asset:
    await project_access(project_id, ident, write=True)
    dest = engine.refs_dir(project_id) / (file.filename or "ref.png")
    # de-dupe filename
    i = 1
    while dest.exists():
        stem, suffix = dest.stem.rstrip("0123456789_"), dest.suffix
        dest = dest.with_name(f"{stem}_{i}{suffix}")
        i += 1
    dest.write_bytes(await file.read())
    asset = Asset(project_id=project_id, node_id=None, kind=AssetKind.ref,
                  path=engine.rel(dest), meta={"filename": file.filename})
    async with session_scope() as s:
        s.add(asset)
        await s.commit()
    return asset


@router.get("/{project_id}/refs")
async def list_refs(project_id: str,
                    ident: Identity = Depends(current_identity)) -> list[Asset]:
    await project_access(project_id, ident)
    return await engine.project_refs(project_id)


@router.get("/{project_id}/tree")
async def get_tree(project_id: str, include_archived: bool = False,
                   ident: Identity = Depends(current_identity)) -> dict:
    """The whole version tree: nodes + their assets + active chains."""
    await project_access(project_id, ident)
    async with session_scope() as s:
        nq = select(Node).where(Node.project_id == project_id).order_by(Node.created_at)
        nodes = list((await s.execute(nq)).scalars())
        if not include_archived:
            nodes = [n for n in nodes if not n.archived]
        aq = select(Asset).where(Asset.project_id == project_id)
        assets = list((await s.execute(aq)).scalars())
        cq = select(Chain).where(Chain.project_id == project_id).order_by(Chain.created_at.desc())
        chains = list((await s.execute(cq)).scalars())
    by_node: dict[str, list] = {}
    for a in assets:
        if a.node_id:
            by_node.setdefault(a.node_id, []).append(a.model_dump())
    return {
        "nodes": [{**n.model_dump(), "assets": by_node.get(n.id, [])} for n in nodes],
        "refs": [a.model_dump() for a in assets if a.kind == AssetKind.ref],
        "chains": [c.model_dump() for c in chains],
    }
