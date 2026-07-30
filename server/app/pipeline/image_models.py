"""Image model registry (verified July 2026): one canonical option set
(prompt, resolution 1k/2k/4k, quality, aspect_ratio, seed) mapped per model to
each provider's real params.

Providers:
- wavespeed:  entry["ws_request"](opts, ref_urls, edit_mode) -> (endpoint, body, est_cost)
- openrouter: entry["map_options"](opts) -> params for the unified Image API
- bfl:        entry["map_options"](opts) -> kwargs for BFLClient.generate
"""
from __future__ import annotations

from typing import Any

from ..clients.wavespeed import estimate_cost as gpt2_cost


def _dims(opts: dict, *, max_side: dict[str, int] | None = None,
          max_mp: float = 4.0, multiple: int = 16) -> tuple[int, int]:
    """resolution tier + aspect_ratio -> (width, height) pixels."""
    side = (max_side or {"1k": 1024, "2k": 2048, "4k": 2048})
    base = side.get(opts.get("resolution") or "2k", 1024)
    try:
        a, b = (opts.get("aspect_ratio") or "1:1").split(":")
        a, b = float(a), float(b)
    except ValueError:
        a = b = 1.0
    w, h = (base, base * b / a) if a >= b else (base * a / b, base)
    mp = w * h / 1e6
    if mp > max_mp:
        s = (max_mp / mp) ** 0.5
        w, h = w * s, h * s
    rnd = lambda v: max(64, int(round(v / multiple)) * multiple)  # noqa: E731
    return rnd(w), rnd(h)


# ---------- wavespeed request builders ----------

def _ws_gpt2(opts, ref_urls, edit_mode):
    body = {"prompt": opts["_prompt"], "aspect_ratio": opts.get("aspect_ratio", "1:1"),
            "resolution": opts.get("resolution", "4k"),
            "quality": opts.get("quality", "high"), "output_format": "png"}
    if ref_urls:
        body["images"] = ref_urls
        return "openai/gpt-image-2/edit", body, gpt2_cost(body["quality"], body["resolution"], len(ref_urls))
    return "openai/gpt-image-2/text-to-image", body, gpt2_cost(body["quality"], body["resolution"], 0)


def _ws_google(path: str, prices: dict[str, float], default_res: str = "2k"):
    def build(opts, ref_urls, edit_mode):
        res = opts.get("resolution") or default_res
        body = {"prompt": opts["_prompt"], "aspect_ratio": opts.get("aspect_ratio", "1:1"),
                "resolution": res, "output_format": "png"}
        cost = prices.get(res, max(prices.values()))
        if ref_urls:
            body["images"] = ref_urls
            return f"{path}/edit", body, cost
        return f"{path}/text-to-image", body, cost
    return build


def _ws_flux2max(opts, ref_urls, edit_mode):
    if ref_urls:
        body = {"prompt": opts["_prompt"], "images": ref_urls}
        if opts.get("seed") is not None:
            body["seed"] = opts["seed"]
        return "wavespeed-ai/flux-2-max/edit", body, 0.07
    w, h = _dims(opts)
    body = {"prompt": opts["_prompt"], "size": f"{w}*{h}",
            "seed": opts.get("seed") if opts.get("seed") is not None else -1}
    return "wavespeed-ai/flux-2-max/text-to-image", body, 0.07


def _ws_luma(opts, ref_urls, edit_mode):
    ar = opts.get("aspect_ratio", "1:1")
    if edit_mode and ref_urls:
        body = {"prompt": opts["_prompt"], "image": ref_urls[0],
                "reference": ref_urls[1:4] or None}
        body = {k: v for k, v in body.items() if v is not None}
        return "luma/uni-v1/edit", body, 0.045 + 0.003 * len(ref_urls[1:4])
    body = {"prompt": opts["_prompt"], "size": ar, "output_format": "png"}
    if ref_urls:
        body["reference"] = ref_urls[:3]
    return "luma/uni-v1/text-to-image", body, 0.042 + 0.003 * len(ref_urls[:3])


# ---------- registry ----------

IMAGE_MODELS: dict[str, dict[str, Any]] = {
    "gpt-image-2 @wavespeed": {
        "provider": "wavespeed", "supports_refs": True, "max_refs": 16,
        "ws_request": _ws_gpt2,
        "notes": "reference model; resolution 1k/2k/4k + quality; refs<=16",
    },
    "gemini-3-pro @wavespeed": {
        "provider": "wavespeed", "supports_refs": True, "max_refs": 14,
        "ws_request": _ws_google("google/nano-banana-pro",
                                 {"1k": 0.14, "2k": 0.14, "4k": 0.24}),
        "notes": "Nano Banana Pro; no quality param; refs<=14; $0.14-0.24",
    },
    "gemini-3.1-flash @wavespeed": {
        "provider": "wavespeed", "supports_refs": True, "max_refs": 14,
        "ws_request": _ws_google("google/nano-banana-2",
                                 {"0.5k": 0.045, "1k": 0.07, "2k": 0.105, "4k": 0.14},
                                 default_res="1k"),
        "notes": "Nano Banana 2; cheap+fast; refs<=14; $0.045-0.14",
    },
    "flux-2-max @wavespeed": {
        "provider": "wavespeed", "supports_refs": True, "max_refs": 3,
        "ws_request": _ws_flux2max,
        "notes": "pixel size from resolution+aspect; seed honored; edit refs<=3; $0.07",
    },
    "luma-uni-1 @wavespeed": {
        "provider": "wavespeed", "supports_refs": True, "max_refs": 3,
        "ws_request": _ws_luma,
        "notes": "aspect preset only (no resolution tiers, ~2k max); refs<=3; ~$0.05",
    },
    "flux-2-max @bfl": {
        "provider": "bfl", "path": "flux-2-max", "supports_refs": True, "max_refs": 8,
        "map_options": lambda opts: (lambda wh: {"width": wh[0], "height": wh[1],
                                                 "seed": opts.get("seed")})(_dims(opts)),
        "notes": "direct BFL; refs<=8; $0.07/MP; seed honored",
    },
    "grok-imagine-quality @openrouter": {
        "provider": "openrouter", "path": "x-ai/grok-imagine-image-quality",
        "supports_refs": True, "max_refs": 3,
        "map_options": lambda opts: {
            "resolution": "1K" if (opts.get("resolution") or "2k") == "1k" else "2K",
            "aspect_ratio": opts.get("aspect_ratio", "1:1"),
        },
        "notes": "xAI quality tier; 1K/2K only; refs<=3; $0.05-0.07 +$0.01/ref",
    },
    "mai-image-2.5 @openrouter": {
        "provider": "openrouter", "path": "microsoft/mai-image-2.5",
        "supports_refs": True, "max_refs": 1,
        "map_options": lambda opts: {"aspect_ratio": opts.get("aspect_ratio", "1:1")},
        "notes": "Microsoft MAI; aspect only, no resolution control; 1 ref; ~$0.10-0.20",
    },
}

DEFAULT_IMAGE_MODEL = "gpt-image-2 @wavespeed"


# legacy option values from before the registry existed
_ALIASES = {
    "openai/gpt-image-2": DEFAULT_IMAGE_MODEL,
    "gpt-image-2": DEFAULT_IMAGE_MODEL,
}


def model_entry(key: str) -> dict[str, Any]:
    key = _ALIASES.get(key, key)
    try:
        return IMAGE_MODELS[key]
    except KeyError:
        raise ValueError(f"unknown image model {key!r}; valid: {list(IMAGE_MODELS)}")
