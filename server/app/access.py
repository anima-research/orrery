"""Ownership checks for per-user libraries.

Rules:
- admins see and touch everything (local mode = synthetic admin, unchanged UX)
- owner (matching durable sub) sees and touches their own projects
- `shared` projects are readable (not writable) by any authenticated user
- legacy projects (owner_sub NULL) belong to admins
"""
from __future__ import annotations

from fastapi import HTTPException

from .auth import Identity
from .db import session_scope
from .models import Asset, Chain, Node, Project


def can_read(p: Project, ident: Identity) -> bool:
    return ident.admin or p.owner_sub == ident.sub or bool(p.shared)


def can_write(p: Project, ident: Identity) -> bool:
    return ident.admin or p.owner_sub == ident.sub


async def project_access(project_id: str, ident: Identity, *, write: bool = False) -> Project:
    async with session_scope() as s:
        p = await s.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    if write and not can_write(p, ident):
        raise HTTPException(403, "not your project")
    if not write and not can_read(p, ident):
        raise HTTPException(404, "project not found")   # don't leak existence
    return p


async def node_access(node_id: str, ident: Identity, *, write: bool = False) -> Node:
    async with session_scope() as s:
        n = await s.get(Node, node_id)
    if not n:
        raise HTTPException(404, "node not found")
    await project_access(n.project_id, ident, write=write)
    return n


async def chain_access(chain_id: str, ident: Identity, *, write: bool = False) -> Chain:
    async with session_scope() as s:
        c = await s.get(Chain, chain_id)
    if not c:
        raise HTTPException(404, "chain not found")
    await project_access(c.project_id, ident, write=write)
    return c


async def asset_access(asset_id: str, ident: Identity, *, write: bool = False) -> Asset:
    async with session_scope() as s:
        a = await s.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "asset not found")
    await project_access(a.project_id, ident, write=write)
    return a
