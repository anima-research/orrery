"""Node executor + chain executor for the version tree.

Execution model:
- Every node runs as its own asyncio task; provider task ids are persisted the
  moment the provider accepts a submission, so a server restart re-attaches to
  in-flight provider work instead of resubmitting.
- Chains poll the DB for their current step's sibling group, so they survive
  restarts too (groups are keyed by chain_id:cursor).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence

from sqlmodel import select

from ..config import get_settings
from ..db import session_scope
from ..models import (
    Asset, AssetKind, Chain, ChainStatus, Node, NodeStatus, OpType, Project, utcnow,
)

log = logging.getLogger(__name__)


class Engine:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._chain_tasks: dict[str, asyncio.Task] = {}

    # ---------- paths ----------

    def node_dir(self, project_id: str, node_id: str) -> Path:
        d = get_settings().projects_dir / project_id / "nodes" / node_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def refs_dir(self, project_id: str) -> Path:
        d = get_settings().projects_dir / project_id / "refs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(get_settings().data_dir.resolve()))

    def abs(self, rel: str) -> Path:
        return get_settings().data_dir / rel

    # ---------- db helpers ----------

    async def get_node(self, node_id: str) -> Node:
        async with session_scope() as s:
            node = await s.get(Node, node_id)
            if not node:
                raise KeyError(f"node {node_id} not found")
            return node

    async def get_project(self, project_id: str) -> Project:
        async with session_scope() as s:
            proj = await s.get(Project, project_id)
            if not proj:
                raise KeyError(f"project {project_id} not found")
            return proj

    async def update_node(self, node_id: str, **fields: Any) -> Node:
        async with session_scope() as s:
            node = await s.get(Node, node_id)
            for k, v in fields.items():
                setattr(node, k, v)
            node.updated_at = utcnow()
            s.add(node)
            await s.commit()
            return node

    async def add_asset(self, node: Node, kind: AssetKind, path: Path,
                        meta: dict | None = None) -> Asset:
        asset = Asset(node_id=node.id, project_id=node.project_id, kind=kind,
                      path=self.rel(path), meta=meta or {})
        async with session_scope() as s:
            s.add(asset)
            await s.commit()
        return asset

    async def update_asset_meta(self, asset_id: str, meta: dict) -> None:
        async with session_scope() as s:
            a = await s.get(Asset, asset_id)
            if a:
                a.meta = {**(a.meta or {}), **meta}
                s.add(a)
                await s.commit()

    async def node_assets(self, node_id: str, kind: AssetKind | None = None) -> list[Asset]:
        async with session_scope() as s:
            q = select(Asset).where(Asset.node_id == node_id)
            if kind:
                q = q.where(Asset.kind == kind)
            return list((await s.execute(q)).scalars().all())

    async def project_refs(self, project_id: str) -> list[Asset]:
        async with session_scope() as s:
            q = select(Asset).where(Asset.project_id == project_id,
                                    Asset.kind == AssetKind.ref)
            return list((await s.execute(q)).scalars().all())

    # ---------- node lifecycle ----------

    async def create_nodes(
        self,
        project_id: str,
        parent_id: Optional[str],
        op_type: OpType,
        options: dict,
        n: int = 1,
        group_id: str | None = None,
        autostart: bool = True,
    ) -> list[Node]:
        group = group_id or (uuid.uuid4().hex[:10] if n > 1 else None)
        nodes = []
        async with session_scope() as s:
            for i in range(n):
                opts = dict(options)
                opts.pop("n", None)
                node = Node(project_id=project_id, parent_id=parent_id,
                            op_type=op_type, options=opts, group_id=group)
                s.add(node)
                nodes.append(node)
            await s.commit()
        if autostart:
            for node in nodes:
                self.schedule(node.id)
        return nodes

    def schedule(self, node_id: str) -> None:
        if node_id in self._tasks and not self._tasks[node_id].done():
            return
        self._tasks[node_id] = asyncio.create_task(self._execute(node_id))

    async def _execute(self, node_id: str) -> None:
        from . import ops  # late import to avoid cycle
        try:
            node = await self.get_node(node_id)
            if node.status in (NodeStatus.completed, NodeStatus.cancelled):
                return
            await self.update_node(node_id, status=NodeStatus.running, error=None)
            impl = ops.OP_IMPLS.get(node.op_type)
            if impl is None:
                raise RuntimeError(f"no implementation for op {node.op_type}")
            await impl(self, await self.get_node(node_id))
            await self.update_node(node_id, status=NodeStatus.completed, progress=100)
        except asyncio.CancelledError:
            await self.update_node(node_id, status=NodeStatus.cancelled)
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("node %s failed", node_id)
            try:
                await self.update_node(node_id, status=NodeStatus.failed, error=str(e)[:2000])
            except Exception:
                pass
        finally:
            self._tasks.pop(node_id, None)

    async def cancel_node(self, node_id: str) -> None:
        task = self._tasks.get(node_id)
        if task and not task.done():
            task.cancel()
        else:
            await self.update_node(node_id, status=NodeStatus.cancelled)

    # ---------- chains ----------

    async def start_chain(self, project_id: str, anchor_node_id: Optional[str],
                          specs: list[dict]) -> Chain:
        chain = Chain(project_id=project_id, anchor_node_id=anchor_node_id, specs=specs)
        async with session_scope() as s:
            s.add(chain)
            await s.commit()
        self._chain_tasks[chain.id] = asyncio.create_task(self._run_chain(chain.id))
        return chain

    async def _group_nodes(self, group_id: str) -> list[Node]:
        async with session_scope() as s:
            q = select(Node).where(Node.group_id == group_id)
            return list((await s.execute(q)).scalars().all())

    async def _run_chain(self, chain_id: str) -> None:
        try:
            while True:
                async with session_scope() as s:
                    chain = await s.get(Chain, chain_id)
                if chain.status in (ChainStatus.completed, ChainStatus.failed,
                                    ChainStatus.cancelled):
                    return
                if chain.cursor >= len(chain.specs):
                    await self._update_chain(chain_id, status=ChainStatus.completed)
                    return
                spec = chain.specs[chain.cursor]
                group_id = f"{chain_id}:{chain.cursor}"
                existing = await self._group_nodes(group_id)
                if not existing:
                    await self.create_nodes(
                        chain.project_id, chain.anchor_node_id,
                        OpType(spec["op"]), spec.get("options") or {},
                        n=max(1, int(spec.get("n") or 1)), group_id=group_id,
                    )
                else:
                    for node in existing:  # restart: re-attach unfinished nodes
                        if node.status in (NodeStatus.pending, NodeStatus.running):
                            self.schedule(node.id)
                selected = await self._await_selection(chain_id, group_id,
                                                       spec.get("select") or "first")
                if selected is None:
                    return  # chain failed/cancelled inside _await_selection
                await self._update_chain(chain_id, anchor_node_id=selected,
                                         cursor=chain.cursor + 1,
                                         status=ChainStatus.running)
        except Exception as e:  # noqa: BLE001
            log.exception("chain %s crashed", chain_id)
            await self._update_chain(chain_id, status=ChainStatus.failed, error=str(e)[:2000])
        finally:
            self._chain_tasks.pop(chain_id, None)

    async def _await_selection(self, chain_id: str, group_id: str, policy: str) -> str | None:
        """Wait until the group resolves; return selected node id, or None if chain ends."""
        while True:
            async with session_scope() as s:
                chain = await s.get(Chain, chain_id)
            if chain.status == ChainStatus.cancelled:
                return None
            nodes = await self._group_nodes(group_id)
            done = [n for n in nodes if n.status == NodeStatus.completed]
            active = [n for n in nodes if n.status in (NodeStatus.pending, NodeStatus.running)]
            if policy == "starred":
                starred = [n for n in done if n.starred]
                if starred:
                    return starred[0].id
                if not active:
                    if not done:
                        await self._update_chain(chain_id, status=ChainStatus.failed,
                                                 error="all candidates failed")
                        return None
                    # everything finished, waiting for a human/agent to star one
                    if chain.status != ChainStatus.waiting_selection:
                        await self._update_chain(chain_id, status=ChainStatus.waiting_selection)
            else:  # "first"
                if done:
                    done.sort(key=lambda n: n.updated_at)
                    return done[0].id
                if not active:
                    await self._update_chain(chain_id, status=ChainStatus.failed,
                                             error="all candidates failed")
                    return None
            await asyncio.sleep(1.0)

    async def _update_chain(self, chain_id: str, **fields: Any) -> None:
        async with session_scope() as s:
            chain = await s.get(Chain, chain_id)
            for k, v in fields.items():
                setattr(chain, k, v)
            chain.updated_at = utcnow()
            s.add(chain)
            await s.commit()

    async def cancel_chain(self, chain_id: str) -> None:
        await self._update_chain(chain_id, status=ChainStatus.cancelled)

    # ---------- startup resume ----------

    async def resume_all(self) -> None:
        async with session_scope() as s:
            q = select(Node).where(Node.status.in_([NodeStatus.pending, NodeStatus.running]))
            nodes = list((await s.execute(q)).scalars().all())
            qc = select(Chain).where(Chain.status.in_(
                [ChainStatus.running, ChainStatus.waiting_selection]))
            chains = list((await s.execute(qc)).scalars().all())
        for node in nodes:
            log.info("resuming node %s (%s)", node.id, node.op_type)
            self.schedule(node.id)
        for chain in chains:
            log.info("resuming chain %s at step %d", chain.id, chain.cursor)
            self._chain_tasks[chain.id] = asyncio.create_task(self._run_chain(chain.id))


engine = Engine()
