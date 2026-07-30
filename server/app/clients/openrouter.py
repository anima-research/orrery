"""OpenRouter unified Image API client (verified 2026-07).

- POST https://openrouter.ai/api/v1/images  (synchronous, no polling)
- refs passed as input_references (http(s) URLs or base64 data URLs)
- images returned as base64 in data[].b64_json; usage.cost = exact USD charged
"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path

import httpx

from ..config import get_settings
from .wavespeed import GenResult

BASE = "https://openrouter.ai/api/v1"


class OpenRouterError(RuntimeError):
    pass


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


class OpenRouterImageClient:
    def __init__(self) -> None:
        s = get_settings()
        self._sem = asyncio.Semaphore(4)
        self._headers = {
            "Authorization": f"Bearer {s.openrouter_api_key}",
            "X-Title": "orrery",
        }

    async def generate(
        self,
        model: str,
        prompt: str,
        dest: Path,
        *,
        ref_paths: list[Path] | None = None,
        params: dict | None = None,   # resolution / aspect_ratio / output_format...
    ) -> GenResult:
        body: dict = {"model": model, "prompt": prompt, "n": 1,
                      "output_format": "png", **(params or {})}
        if ref_paths:
            body["input_references"] = [
                {"type": "image_url", "image_url": {"url": _data_url(p)}} for p in ref_paths
            ]
        async with self._sem:
            async with httpx.AsyncClient(timeout=600) as client:
                r = await client.post(f"{BASE}/images", headers=self._headers, json=body)
        if r.status_code == 402:
            raise OpenRouterError("openrouter: out of credits (402)")
        if r.status_code == 429:
            raise OpenRouterError("openrouter: rate limited (429)")
        if r.status_code >= 400:
            raise OpenRouterError(f"openrouter {r.status_code}: {r.text[:300]}")
        payload = r.json()
        data = payload.get("data") or []
        if not data or not data[0].get("b64_json"):
            raise OpenRouterError(f"no image in response: {str(payload)[:300]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(data[0]["b64_json"]))
        cost = float((payload.get("usage") or {}).get("cost") or 0.0)
        return GenResult(prediction_id=f"or-{payload.get('created', 0)}",
                         image_path=dest, cost_usd=cost)
