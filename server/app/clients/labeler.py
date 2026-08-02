"""Vision pass: read which orthographic view sits in each grid pane.

gpt-image-2 (and friends) frequently place the left/right side views in the
wrong panes. Haiku 4.5 looks at the raw 2x2 grid and reports the actual view in
each pane, so `split` can permute the crop instead of trusting the contract.

Front/back are reliable; left/right is the hard call — the model disambiguates
the two profiles by consistency with the front view (asymmetric details, facing
direction), and if it can't produce a clean permutation we fall back to the
default layout (and the human can still relabel).
"""
from __future__ import annotations

import base64
import io
import logging

from PIL import Image

from ..config import get_settings

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
PANE_POS = {  # pane name -> (col, row) in the 2x2 grid
    "top_left": (0, 0), "top_right": (1, 0),
    "bottom_left": (0, 1), "bottom_right": (1, 1),
}
_VIEWS = ["front", "left", "back", "right"]
_SCHEMA = {
    "type": "object",
    "properties": {p: {"type": "string", "enum": _VIEWS} for p in PANE_POS},
    "required": list(PANE_POS),
    "additionalProperties": False,
}
_PROMPT = (
    "This image is a 2x2 grid showing four orthographic turnaround views of a single "
    "object, one per pane. Identify which view each pane holds.\n"
    "Definitions (object-relative):\n"
    "- front: the object faces the camera (you see its front).\n"
    "- back: the object faces away (you see its back).\n"
    "- left: the object's OWN left side faces the camera (a left profile).\n"
    "- right: the object's OWN right side faces the camera (a right profile).\n"
    "The two profile panes are mirror images; tell them apart using asymmetric details "
    "and facing direction, staying consistent with the front pane. Report the view in "
    "each of the four panes (top_left, top_right, bottom_left, bottom_right)."
)


async def label_grid(path) -> dict[str, tuple[int, int]] | None:
    """Return {view: (col, row)} from a vision read of the grid, or None if the
    labeler is unavailable or didn't yield a clean 4-view permutation."""
    s = get_settings()
    if s.mock_apis or not s.anthropic_api_key:
        return None
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        log.warning("anthropic sdk not installed; skipping auto-label")
        return None

    # downscale to keep the request cheap — pane identity survives easily at 768px
    img = Image.open(path).convert("RGB")
    img.thumbnail((768, 768))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode()

    client = AsyncAnthropic(api_key=s.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=200,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("auto-label request failed: %s", e)
        return None

    import json
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        return None
    try:
        assignment = json.loads(text)  # {pane: view}
    except Exception:
        return None

    views = [assignment.get(p) for p in PANE_POS]
    if sorted(v for v in views if v) != sorted(_VIEWS):  # not a clean permutation
        log.info("auto-label produced %s — not a permutation, using default", views)
        return None
    return {assignment[pane]: PANE_POS[pane] for pane in PANE_POS}
