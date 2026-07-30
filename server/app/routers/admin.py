"""Admin-only views across all users' libraries."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from ..auth import Identity, current_identity
from ..db import session_scope
from ..models import Asset, Node, NodeStatus, Project

router = APIRouter(prefix="/api/admin", tags=["admin"])

# thumbnail preference per node, same order the tree panel uses
_THUMB_ORDER = ["screenshot", "render", "grid", "view"]


def require_admin(ident: Identity = Depends(current_identity)) -> Identity:
    if not ident.admin:
        raise HTTPException(403, "admin only")
    return ident


@router.get("/recent")
async def recent_activity(limit: int = 40,
                          ident: Identity = Depends(require_admin)) -> list[dict]:
    """Latest generation nodes across every user's library, with thumbnails."""
    limit = max(1, min(200, limit))
    async with session_scope() as s:
        nodes = list((await s.execute(
            select(Node).where(Node.status != NodeStatus.pending)
            .order_by(Node.created_at.desc()).limit(limit))).scalars())
        pids = {n.project_id for n in nodes}
        projects = {p.id: p for p in (await s.execute(
            select(Project).where(Project.id.in_(pids)))).scalars()}
        assets = list((await s.execute(
            select(Asset).where(Asset.node_id.in_([n.id for n in nodes])))).scalars())
    by_node: dict[str, list[Asset]] = {}
    for a in assets:
        by_node.setdefault(a.node_id, []).append(a)

    out = []
    for n in nodes:
        p = projects.get(n.project_id)
        thumb = None
        node_assets = by_node.get(n.id, [])
        for kind in _THUMB_ORDER:
            hit = next((a for a in node_assets if a.kind == kind), None)
            if hit:
                thumb = hit.id
                break
        out.append({
            "node_id": n.id, "op_type": n.op_type, "status": n.status,
            "created_at": n.created_at.isoformat(),
            "cost_usd": n.cost_usd, "credits": n.credits,
            "project_id": n.project_id,
            "project_name": p.name if p else "?",
            "owner_name": (p.owner_name or p.owner_sub or "legacy") if p else "?",
            "thumb_asset": thumb,
            "has_model": any(a.kind == "model" for a in node_assets),
        })
    return out


@router.get("/users")
async def user_totals(ident: Identity = Depends(require_admin)) -> list[dict]:
    """Spend + volume per owner."""
    async with session_scope() as s:
        projects = list((await s.execute(select(Project))).scalars())
        nodes = list((await s.execute(select(Node))).scalars())
    proj_owner = {p.id: (p.owner_name or p.owner_sub or "legacy") for p in projects}
    totals: dict[str, dict] = {}
    for p in projects:
        t = totals.setdefault(proj_owner[p.id], {"owner": proj_owner[p.id],
                                                 "projects": 0, "nodes": 0,
                                                 "cost_usd": 0.0, "credits": 0})
        t["projects"] += 1
    for n in nodes:
        owner = proj_owner.get(n.project_id, "?")
        t = totals.setdefault(owner, {"owner": owner, "projects": 0, "nodes": 0,
                                      "cost_usd": 0.0, "credits": 0})
        t["nodes"] += 1
        t["cost_usd"] = round(t["cost_usd"] + n.cost_usd, 3)
        t["credits"] += n.credits
    return sorted(totals.values(), key=lambda t: -(t["cost_usd"] + t["credits"] / 100))
