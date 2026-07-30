"""The 4-pane grid contract, shared by the prompt template AND the splitter.

GRID_LAYOUT maps view name -> (col, row) in a 2x2 grid:
    TL front | TR left
    BL back  | BR right
Tripo's canonical multiview order is [front, left, back, right].
"""
from __future__ import annotations

GRID_LAYOUT: dict[str, tuple[int, int]] = {
    "front": (0, 0),
    "left": (1, 0),
    "back": (0, 1),
    "right": (1, 1),
}

VIEW_ORDER = ["front", "left", "back", "right"]

_POSITION_WORDS = {(0, 0): "top-left", (1, 0): "top-right", (0, 1): "bottom-left", (1, 1): "bottom-right"}

GRID_CONTRACT = (
    "Render a single image divided into a 2x2 grid of four equal panes on a plain, uniform "
    "light-gray background with thin separation between panes. Each pane shows the SAME single "
    "object as an orthographic-style turnaround view, identical scale, centered, consistent "
    "neutral studio lighting, no shadows touching pane borders, no text or labels: "
    + "; ".join(
        f"{_POSITION_WORDS[pos]} pane: {view} view" +
        {
            "front": " (object facing the camera)",
            "left": " (object's left side profile, rotated 90 degrees)",
            "back": " (object seen directly from behind)",
            "right": " (object's right side profile, rotated -90 degrees)",
        }[view]
        for view, pos in GRID_LAYOUT.items()
    )
    + ". The object must be fully visible inside each pane with margin."
)

# Toggleable suffix for character/creature subjects (Tripo's rigger expects T-pose).
CHARACTER_SUFFIX = (
    "The subject is a character: pose it in a strict T-pose — arms fully extended straight "
    "out to the sides at shoulder height, palms down, fingers straight, legs straight and "
    "slightly apart, head level, mouth closed, identical pose in every view."
)


def assemble_prompt(subject: str, opts: dict) -> str:
    """subject + [character suffix if enabled] + [grid contract if enabled]."""
    parts = [subject.strip()]
    if opts.get("character"):
        parts.append((opts.get("character_suffix") or CHARACTER_SUFFIX).strip())
    if opts.get("grid_contract", True):
        parts.append((opts.get("contract") or GRID_CONTRACT).strip())
    return "\n\n".join(p for p in parts if p)
