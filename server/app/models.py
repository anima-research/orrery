"""SQLModel tables: the append-only version tree.

A Node is one operation applied to its parent node's output, with a full
options snapshot. Retry = new sibling. Nothing is ever mutated or deleted;
`archived` only hides a node in the UI.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OpType(str, enum.Enum):
    ref_set = "ref_set"          # container of reference images (branchable input set)
    image_gen = "image_gen"      # WaveSpeed image model; t2i at root, edit under a ref_set
    image_edit = "image_edit"    # img2img on the parent node's image, custom prompt
    split = "split"              # cut 2x2 grid into 4 view files (local)
    mesh_gen = "mesh_gen"        # Tripo multiview-to-model
    image_to_multiview = "image_to_multiview"  # Tripo alternative front-end
    texture = "texture"          # Tripo models/texture
    retopo = "retopo"            # Tripo mesh/decimate
    segment = "segment"          # Tripo mesh/segment
    complete = "complete"        # Tripo mesh/complete
    rig = "rig"                  # Tripo rig-check + rig
    retarget = "retarget"        # Tripo animations/retarget
    convert = "convert"          # Tripo models/convert
    import_model = "import_model"  # external model file into the tree


class NodeStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Project(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    name: str
    prompt: str = ""             # default subject prompt for the project
    owner_sub: Optional[str] = Field(default=None, index=True)  # archipelago sub; None = legacy/admin
    owner_name: str = ""
    shared: bool = False         # visible read-only to all logged-in users
    created_at: datetime = Field(default_factory=utcnow)


class Node(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    project_id: str = Field(index=True, foreign_key="project.id")
    parent_id: Optional[str] = Field(default=None, index=True)
    op_type: OpType
    options: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    group_id: Optional[str] = Field(default=None, index=True)  # siblings launched together
    provider: Optional[str] = None            # wavespeed | tripo | local
    provider_task_id: Optional[str] = Field(default=None, index=True)
    status: NodeStatus = Field(default=NodeStatus.pending, index=True)
    progress: int = 0                         # 0-100
    error: Optional[str] = None
    cost_usd: float = 0.0                     # wavespeed spend (estimated from price table)
    credits: int = 0                          # tripo credits_consumed
    starred: bool = False
    archived: bool = False
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChainStatus(str, enum.Enum):
    running = "running"
    waiting_selection = "waiting_selection"   # select policy 'starred' waiting on a human/agent star
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Chain(SQLModel, table=True):
    """A queued sequence of op specs walked down the tree automatically.

    specs: [{"op": "mesh_gen", "options": {...}, "n": 2, "select": "first"|"starred"}, ...]
    Resumable: cursor advances only after a step's group resolves; groups are
    keyed group_id = f"{chain_id}:{cursor}" so restarts re-attach to in-flight nodes.
    """
    id: str = Field(default_factory=_id, primary_key=True)
    project_id: str = Field(index=True, foreign_key="project.id")
    anchor_node_id: Optional[str] = None      # node the NEXT step branches from; None => first step creates roots
    specs: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    cursor: int = 0
    status: ChainStatus = Field(default=ChainStatus.running, index=True)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AssetKind(str, enum.Enum):
    ref = "ref"
    grid = "grid"                # the 4-pane image
    view = "view"                # single front/left/back/right pane
    model = "model"              # glb/fbx/...
    render = "render"            # provider-rendered preview image
    screenshot = "screenshot"    # our headless turntable render


class Asset(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    node_id: Optional[str] = Field(default=None, index=True)   # None => project-level (refs)
    project_id: str = Field(index=True, foreign_key="project.id")
    kind: AssetKind
    path: str                    # relative to settings.data_dir
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
