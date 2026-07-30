"""Async Tripo v3 client.

API facts (verified 2026-07):
- Base https://openapi.tripo3d.ai/v3, Bearer auth, envelope {"code":0,"data":{...}}.
- POST /v3/files (multipart 'file') -> data.file_token  (images <=20MB, models <=150MB)
- Generation/processing endpoints -> {task_id}; poll GET /v3/tasks/{task_id}
  status: queued|running|success|failed|cancelled|banned|expired, progress 0-100,
  output.model_url / rendered_image_url / view urls; credits_consumed.
- Post-processing endpoints take input = task_id | file_token | URL.
- Output URLs are short-lived -> caller archives immediately.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

BASE = "https://openapi.tripo3d.ai/v3"

TERMINAL = {"success", "failed", "cancelled", "banned", "expired"}


class TripoError(RuntimeError):
    def __init__(self, msg: str, code: int | None = None):
        super().__init__(msg)
        self.code = code


@dataclass
class TaskResult:
    task_id: str
    status: str
    progress: int
    output: dict
    credits: int
    raw: dict


class TripoClient:
    def __init__(self) -> None:
        s = get_settings()
        self._sem = asyncio.Semaphore(s.tripo_max_concurrency)
        self._headers = {"Authorization": f"Bearer {s.tripo_api_key}"}

    async def _unwrap(self, r: httpx.Response) -> dict:
        if r.status_code == 429:
            raise TripoError("rate/concurrency limited (429)", code=2000)
        try:
            payload = r.json()
        except Exception:
            r.raise_for_status()
            raise TripoError(f"non-JSON response: {r.text[:300]}")
        if payload.get("code") != 0:
            raise TripoError(
                f"tripo error code={payload.get('code')}: {payload.get('message')} "
                f"(suggestion: {payload.get('suggestion')})",
                code=payload.get("code"),
            )
        return payload["data"]

    async def upload_file(self, path: Path) -> str:
        """Upload local file -> file_token."""
        async with httpx.AsyncClient(timeout=600) as client:
            with open(path, "rb") as f:
                r = await client.post(
                    f"{BASE}/files", headers=self._headers, files={"file": (path.name, f)}
                )
        data = await self._unwrap(r)
        token = data.get("file_token") or data.get("token")
        if not token:
            raise TripoError(f"upload returned no file_token: {data}")
        return token

    async def create_task(self, endpoint: str, payload: dict) -> str:
        """POST a task creation endpoint (path relative to /v3), return task_id."""
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{BASE}/{endpoint.lstrip('/')}", headers=self._headers, json=payload)
        data = await self._unwrap(r)
        task_id = data.get("task_id")
        if not task_id:
            raise TripoError(f"no task_id in response: {data}")
        return task_id

    async def get_task(self, task_id: str) -> TaskResult:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{BASE}/tasks/{task_id}", headers=self._headers)
        data = await self._unwrap(r)
        return TaskResult(
            task_id=task_id,
            status=data.get("status", "unknown"),
            progress=int(data.get("progress") or 0),
            output=data.get("output") or {},
            credits=int(data.get("credits_consumed") or 0),
            raw=data,
        )

    async def poll(
        self,
        task_id: str,
        on_progress: Optional[Callable[[int], Awaitable[None]]] = None,
    ) -> TaskResult:
        s = get_settings()
        delay = 1.5
        last_progress = -1
        while True:
            res = await self.get_task(task_id)
            if res.progress != last_progress and on_progress:
                last_progress = res.progress
                await on_progress(res.progress)
            if res.status in TERMINAL:
                return res
            await asyncio.sleep(delay)
            delay = min(delay * 1.3, s.poll_max_seconds)

    async def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return dest

    async def run_task(
        self,
        endpoint: str,
        payload: dict,
        *,
        on_submit: Optional[Callable[[str], Awaitable[None]]] = None,
        on_progress: Optional[Callable[[int], Awaitable[None]]] = None,
        existing_task_id: str | None = None,
    ) -> TaskResult:
        """Create (or resume) + poll one task, semaphore-guarded. Raises on failure."""
        async with self._sem:
            task_id = existing_task_id
            if not task_id:
                task_id = await self.create_task(endpoint, payload)
                if on_submit:
                    await on_submit(task_id)
            res = await self.poll(task_id, on_progress)
        if res.status != "success":
            detail = res.raw.get("error_message") or res.raw.get("error_code") or res.status
            raise TripoError(f"task {task_id} ({endpoint}) -> {res.status}: {detail}")
        return res

    async def balance(self) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{BASE}/account/balance", headers=self._headers)
        return await self._unwrap(r)
