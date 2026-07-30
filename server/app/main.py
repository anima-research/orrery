"""orrery server: reference images + prompts -> 3D models, as a version tree."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .pipeline.engine import engine
from .routers import assets, authr, nodes, projects, quick, screenshots

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


async def _migrate_project_refs() -> None:
    """Legacy: move project-level reference assets into a ref_set node so all
    references live in the tree."""
    from sqlmodel import select
    from .db import session_scope
    from .models import Asset, AssetKind, Node, NodeStatus, OpType

    async with session_scope() as s:
        q = select(Asset).where(Asset.kind == AssetKind.ref, Asset.node_id.is_(None))
        orphans = list((await s.execute(q)).scalars().all())
        if not orphans:
            return
        by_project: dict[str, list[Asset]] = {}
        for a in orphans:
            by_project.setdefault(a.project_id, []).append(a)
        for pid, assets in by_project.items():
            node = Node(project_id=pid, parent_id=None, op_type=OpType.ref_set,
                        options={}, status=NodeStatus.completed, progress=100,
                        provider="local", note="migrated project references")
            s.add(node)
            await s.flush()
            for a in assets:
                a.node_id = node.id
                s.add(a)
        await s.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _migrate_project_refs()
    await engine.resume_all()
    yield


app = FastAPI(title="orrery", version="0.1.0", lifespan=lifespan)

app.include_router(authr.router)
app.include_router(projects.router)
app.include_router(nodes.router)
app.include_router(assets.router)
app.include_router(quick.router)
app.include_router(screenshots.router)


AGENTS_MD = Path(__file__).resolve().parent / "static" / "AGENTS.md"


@app.get("/agents.md", include_in_schema=False)
@app.get("/api/agents.md", include_in_schema=False)
async def agents_guide():
    """Practical API guide for agents — served as raw markdown."""
    return FileResponse(AGENTS_MD, media_type="text/markdown; charset=utf-8")


@app.get("/api/health")
async def health() -> dict:
    s = get_settings()
    return {"ok": True, "mock": s.mock_apis,
            "keys": {"wavespeed": bool(s.wavespeed_api_key), "tripo": bool(s.tripo_api_key)}}


# Serve the built UI (web/dist) if present; SPA fallback to index.html.
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")


def run() -> None:
    import uvicorn
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=False)


if __name__ == "__main__":
    run()
