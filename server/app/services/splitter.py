"""Cut a 2x2 grid image into four view PNGs using the shared GRID_LAYOUT."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..pipeline.prompts import GRID_LAYOUT

# Fraction of each pane trimmed from every edge to drop grid separator lines.
DEFAULT_TRIM = 0.01


def split_grid(
    grid_path: Path,
    out_dir: Path,
    mapping: dict[str, tuple[int, int]] | None = None,
    trim: float = DEFAULT_TRIM,
) -> dict[str, Path]:
    """Returns {view_name: png_path}. `mapping` overrides pane assignment
    (e.g. user swaps left/right) — values are (col, row) in the 2x2 grid."""
    layout = {k: tuple(v) for k, v in (mapping or GRID_LAYOUT).items()}
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(grid_path).convert("RGB")
    w, h = img.size
    pw, ph = w // 2, h // 2
    tx, ty = int(pw * trim), int(ph * trim)
    out: dict[str, Path] = {}
    for view, (col, row) in layout.items():
        box = (col * pw + tx, row * ph + ty, (col + 1) * pw - tx, (row + 1) * ph - ty)
        pane = img.crop(box)
        dest = out_dir / f"{view}.png"
        pane.save(dest)
        out[view] = dest
    return out
