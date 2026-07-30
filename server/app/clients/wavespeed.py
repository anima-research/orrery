"""Async WaveSpeed client for gpt-image-2 (text-to-image + edit).

API facts (verified 2026-07):
- POST /api/v3/openai/gpt-image-2/text-to-image  {prompt, aspect_ratio, resolution, quality, output_format}
- POST /api/v3/openai/gpt-image-2/edit           same + images: [url, ...] (1-16)
- POST /api/v3/media/upload/binary               multipart 'file' -> data.download_url (kept 7 days)
- GET  /api/v3/predictions/{id}/result           status: created|processing|completed|failed|cancelled|timeout
- No n/seed params: N candidates = N parallel requests.
- Output URLs live ~7 days -> caller archives immediately.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

BASE = "https://api.wavespeed.ai/api/v3"

# USD per image: (endpoint, quality, resolution) -> price. Edit adds $0.012 per extra input.
PRICES = {
    ("t2i", "low", "1k"): 0.01, ("t2i", "low", "2k"): 0.02, ("t2i", "low", "4k"): 0.03,
    ("t2i", "medium", "1k"): 0.06, ("t2i", "medium", "2k"): 0.10, ("t2i", "medium", "4k"): 0.18,
    ("t2i", "high", "1k"): 0.22, ("t2i", "high", "2k"): 0.40, ("t2i", "high", "4k"): 0.72,
    ("edit", "low", "1k"): 0.02, ("edit", "low", "2k"): 0.03, ("edit", "low", "4k"): 0.04,
    ("edit", "medium", "1k"): 0.07, ("edit", "medium", "2k"): 0.11, ("edit", "medium", "4k"): 0.19,
    ("edit", "high", "1k"): 0.23, ("edit", "high", "2k"): 0.41, ("edit", "high", "4k"): 0.73,
}
EXTRA_INPUT_PRICE = 0.012

TERMINAL = {"completed", "failed", "cancelled", "timeout"}


def estimate_cost(quality: str, resolution: str, n_inputs: int) -> float:
    kind = "edit" if n_inputs else "t2i"
    base = PRICES.get((kind, quality, resolution), 0.0)
    extra = EXTRA_INPUT_PRICE * max(0, n_inputs - 1)
    return round(base + extra, 4)


@dataclass
class GenResult:
    prediction_id: str
    image_path: Path
    cost_usd: float
    inference_ms: int = 0


class WaveSpeedError(RuntimeError):
    pass


class WaveSpeedClient:
    def __init__(self) -> None:
        s = get_settings()
        self._sem = asyncio.Semaphore(s.wavespeed_max_concurrency)
        self._headers = {"Authorization": f"Bearer {s.wavespeed_api_key}"}
        self._upload_cache: dict[str, str] = {}  # local path -> uploaded url

    async def upload_ref(self, path: Path) -> str:
        """Upload a local reference image, return a WaveSpeed-hosted URL (cached)."""
        key = str(path.resolve())
        if key in self._upload_cache:
            return self._upload_cache[key]
        async with httpx.AsyncClient(timeout=120) as client:
            with open(path, "rb") as f:
                r = await client.post(
                    f"{BASE}/media/upload/binary",
                    headers=self._headers,
                    files={"file": (path.name, f)},
                )
        r.raise_for_status()
        data = r.json().get("data") or {}
        url = data.get("download_url") or data.get("url")
        if not url:
            raise WaveSpeedError(f"upload returned no URL: {r.text[:300]}")
        self._upload_cache[key] = url
        return url

    async def poll(self, prediction_id: str) -> dict:
        """Poll until terminal; returns the final prediction data dict."""
        s = get_settings()
        delay = s.poll_initial_seconds
        async with httpx.AsyncClient(timeout=60) as client:
            while True:
                r = await client.get(
                    f"{BASE}/predictions/{prediction_id}/result", headers=self._headers
                )
                r.raise_for_status()
                data = r.json().get("data") or {}
                status = data.get("status")
                if status in TERMINAL:
                    return data
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, s.poll_max_seconds)

    async def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return dest

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
        """Generic: submit any model endpoint + poll + archive one image.
        Semaphore-guarded end to end. existing_prediction_id resumes a
        previously-submitted prediction (restart safety)."""
        async with self._sem:
            pred_id = existing_prediction_id
            if not pred_id:
                async with httpx.AsyncClient(timeout=60) as client:
                    r = await client.post(f"{BASE}/{endpoint.lstrip('/')}",
                                          headers=self._headers, json=body)
                if r.status_code == 429:
                    raise WaveSpeedError("rate limited (429) — check account tier concurrency")
                r.raise_for_status()
                pred_id = (r.json().get("data") or {}).get("id")
                if not pred_id:
                    raise WaveSpeedError(f"no prediction id in response: {r.text[:300]}")
                if on_submit:
                    await on_submit(pred_id)
            data = await self.poll(pred_id)
        if data.get("status") != "completed":
            raise WaveSpeedError(
                f"prediction {pred_id} {data.get('status')}: {data.get('error') or 'no error detail'}"
            )
        outputs = data.get("outputs") or []
        if not outputs:
            raise WaveSpeedError(f"prediction {pred_id} completed with no outputs")
        await self.download(outputs[0], dest)
        return GenResult(
            prediction_id=pred_id,
            image_path=dest,
            cost_usd=cost_usd,
            inference_ms=int((data.get("timings") or {}).get("inference") or 0),
        )
