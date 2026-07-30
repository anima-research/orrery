"""Mock provider clients: same surface as the real ones, canned outputs."""
from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Optional

from . import fixtures
from .tripo import TaskResult
from .wavespeed import GenResult

MOCK_LATENCY = 0.4


class MockWaveSpeedClient:
    async def upload_ref(self, path: Path) -> str:
        return f"mock://wavespeed/{path.name}"

    async def run(
        self,
        endpoint: str,
        body: dict,
        dest: Path,
        *,
        cost_usd: float = 0.0,
        on_submit: Optional[Callable[[str], Awaitable[None]]] = None,
        existing_prediction_id: str | None = None,
    ) -> GenResult:
        pred_id = existing_prediction_id or f"mock-{uuid.uuid4().hex[:8]}"
        if on_submit and not existing_prediction_id:
            await on_submit(pred_id)
        await asyncio.sleep(MOCK_LATENCY)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fixtures.grid_image(), dest)
        return GenResult(prediction_id=pred_id, image_path=dest, cost_usd=0.0)


class MockTripoClient:
    async def upload_file(self, path: Path) -> str:
        return f"mock-token-{uuid.uuid4().hex[:8]}"

    async def run_task(
        self,
        endpoint: str,
        payload: dict,
        *,
        on_submit: Optional[Callable[[str], Awaitable[None]]] = None,
        on_progress: Optional[Callable[[int], Awaitable[None]]] = None,
        existing_task_id: str | None = None,
    ) -> TaskResult:
        task_id = existing_task_id or f"mock-{uuid.uuid4().hex[:8]}"
        if on_submit and not existing_task_id:
            await on_submit(task_id)
        for p in (25, 60, 90):
            await asyncio.sleep(MOCK_LATENCY / 3)
            if on_progress:
                await on_progress(p)
        output: dict = {}
        if "rig-check" in endpoint:
            output = {"riggable": True, "rig_type": "biped"}
        else:
            output = {
                "model_url": f"mock://tripo/{task_id}.glb",
                "rendered_image_url": f"mock://tripo/{task_id}.png",
            }
        return TaskResult(task_id=task_id, status="success", progress=100,
                          output=output, credits=0, raw={"mock": True})

    async def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = fixtures.cube_glb() if url.endswith(".glb") or dest.suffix in {".glb", ".fbx", ".obj", ".usdz", ".stl"} else fixtures.render_image()
        shutil.copy(src, dest)
        return dest

    async def balance(self) -> dict:
        return {"balance": 99999, "frozen": 0}
