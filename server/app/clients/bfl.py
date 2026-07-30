"""Black Forest Labs direct API client (verified 2026-07).

- POST https://api.bfl.ai/v1/{model}   auth header: x-key
- up to 8 input images (https URL or data: URI), width/height <= 4MP total
- async: submit -> {id, polling_url, cost(credits)}; poll polling_url until
  status Ready; image at result.sample — URL EXPIRES IN 10 MIN, download now.
- pricing: megapixel-based, actual charged credits in submit response (1cr=$0.01)
"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path

import httpx

from ..config import get_settings
from .wavespeed import GenResult

BASE = "https://api.bfl.ai/v1"
TERMINAL = {"Ready", "Error", "Request Moderated", "Content Moderated", "Task not found"}


class BFLError(RuntimeError):
    pass


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


class BFLClient:
    def __init__(self) -> None:
        s = get_settings()
        self._sem = asyncio.Semaphore(8)   # account cap is 24 concurrent
        self._headers = {"x-key": s.blackforest_api_key}

    async def generate(
        self,
        model: str,                       # e.g. "flux-2-max"
        prompt: str,
        dest: Path,
        *,
        ref_paths: list[Path] | None = None,
        width: int | None = None,
        height: int | None = None,
        seed: int | None = None,
    ) -> GenResult:
        body: dict = {"prompt": prompt, "output_format": "png", "safety_tolerance": 2}
        if width and height:
            body["width"], body["height"] = width, height
        if seed is not None:
            body["seed"] = seed
        for i, p in enumerate((ref_paths or [])[:8]):
            body["input_image" if i == 0 else f"input_image_{i + 1}"] = _data_uri(p)

        async with self._sem:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(f"{BASE}/{model}", headers=self._headers, json=body)
            if r.status_code == 429:
                raise BFLError("bfl: too many concurrent tasks (429)")
            if r.status_code >= 400:
                raise BFLError(f"bfl {r.status_code}: {r.text[:300]}")
            sub = r.json()
            task_id, poll_url = sub.get("id"), sub.get("polling_url")
            credits = float(sub.get("cost") or 0.0)
            if not poll_url:
                raise BFLError(f"no polling_url in response: {str(sub)[:200]}")

            async with httpx.AsyncClient(timeout=60) as client:
                while True:
                    pr = await client.get(poll_url, headers=self._headers,
                                          params={"id": task_id})
                    pr.raise_for_status()
                    data = pr.json()
                    status = data.get("status")
                    if status in TERMINAL:
                        break
                    await asyncio.sleep(1.0)
            if status != "Ready":
                raise BFLError(f"bfl task {task_id}: {status} — {str(data.get('details'))[:200]}")
            sample = (data.get("result") or {}).get("sample")
            if not sample:
                raise BFLError(f"bfl task {task_id}: Ready but no result.sample")
            # result URLs die in 10 minutes — download immediately
            dest.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
                img = await client.get(sample)
                img.raise_for_status()
                dest.write_bytes(img.content)
        return GenResult(prediction_id=task_id or "bfl", image_path=dest,
                         cost_usd=round(credits * 0.01, 4))
