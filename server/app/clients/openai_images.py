"""Direct OpenAI Images API client (verified 2026-09-08 against gpt-image-2.5).

gpt-image-2.5-flare / -sunburst are Images-API ONLY (Responses -> 404, chat ->
503); gpt-image-2 is on the same endpoint with the same params.

- POST /v1/images/generations   json  {model, prompt, size, quality, output_format, n}
- POST /v1/images/edits         multipart, same fields + image[] files (<=16)
- size: "auto" or any WxH, both %16, longest edge <= 3840, pixel budget
  8,294,400 (= 3840x2160) — all three models.  quality: low|medium|high|auto.
  output_format: png|webp|jpeg.  background: transparent|opaque|auto.
  input_fidelity is REJECTED by 2.5-flare/-sunburst and gpt-image-2 (400).
- synchronous (10-60 s), image returned base64 in data[].b64_json,
  usage {input_tokens, output_tokens, input_tokens_details{text_tokens,image_tokens}}
  -> cost computed from the per-model token price table below.
"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path

import httpx

from ..config import get_settings
from .wavespeed import GenResult

BASE = "https://api.openai.com/v1"

# USD per 1M tokens: (text in, image in, image out). 2.5 rates from the 09-08
# pricing page; gpt-image-2 direct is billed the same way (rates assumed equal —
# the usage block is exact, only the multiplier is an estimate).
TOKEN_PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-image-2.5-flare": (5.0, 8.0, 30.0),
    "gpt-image-2.5-sunburst": (5.0, 8.0, 30.0),
    "gpt-image-2": (5.0, 8.0, 30.0),
}


class OpenAIImagesError(RuntimeError):
    pass


def cost_from_usage(model: str, usage: dict | None) -> float:
    """Exact-token cost: usage.input_tokens_details splits text/image input."""
    if not usage:
        return 0.0
    text_p, img_in_p, img_out_p = TOKEN_PRICES.get(model, (5.0, 8.0, 30.0))
    details = usage.get("input_tokens_details") or {}
    img_in = int(details.get("image_tokens") or 0)
    text_in = int(details.get("text_tokens") or (int(usage.get("input_tokens") or 0) - img_in))
    out = int(usage.get("output_tokens") or 0)
    return round((text_in * text_p + img_in * img_in_p + out * img_out_p) / 1e6, 4)


class OpenAIImagesClient:
    def __init__(self) -> None:
        s = get_settings()
        self._sem = asyncio.Semaphore(s.openai_images_max_concurrency)
        self._headers = {"Authorization": f"Bearer {s.openai_api_key}"}

    async def generate(
        self,
        model: str,
        prompt: str,
        dest: Path,
        *,
        ref_paths: list[Path] | None = None,
        params: dict | None = None,   # size / quality / background
    ) -> GenResult:
        """One image. With ref_paths -> /images/edits (multipart), else
        /images/generations (json)."""
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        refs = list(ref_paths or [])[:16]
        async with self._sem:
            async with httpx.AsyncClient(timeout=600) as client:
                if refs:
                    data = {"model": model, "prompt": prompt, "n": "1", "output_format": "png",
                            **{k: str(v) for k, v in params.items()}}
                    files = []
                    handles = []
                    try:
                        for p in refs:
                            fh = open(p, "rb")
                            handles.append(fh)
                            mime = mimetypes.guess_type(p.name)[0] or "image/png"
                            files.append(("image[]", (p.name, fh, mime)))
                        r = await client.post(f"{BASE}/images/edits", headers=self._headers,
                                              data=data, files=files)
                    finally:
                        for fh in handles:
                            fh.close()
                else:
                    body ={"model": model, "prompt": prompt, "n": 1, "output_format": "png",
                            **params}
                    r = await client.post(f"{BASE}/images/generations", headers=self._headers,
                                          json=body)
        if r.status_code == 429:
            raise OpenAIImagesError("openai images: rate limited (429)")
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = r.text[:300]
            raise OpenAIImagesError(f"openai images {r.status_code}: {msg}")
        payload = r.json()
        items = payload.get("data") or []
        if not items or not items[0].get("b64_json"):
            raise OpenAIImagesError(f"no image in response: {str(payload)[:300]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(items[0]["b64_json"]))
        return GenResult(prediction_id=f"oai-{payload.get('created', 0)}",
                         image_path=dest, cost_usd=cost_from_usage(model, payload.get("usage")))
