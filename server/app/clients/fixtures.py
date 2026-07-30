"""Offline fixtures for MOCK_APIS mode: a synthetic 4-pane grid image and a
minimal-but-valid GLB (colored cube), both generated on first use."""
from __future__ import annotations

import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def grid_image(size: int = 1024) -> Path:
    """A 2x2 grid: TL front / TR left / BL back / BR right, visually distinct."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    dest = FIXTURE_DIR / f"grid_{size}.png"
    if dest.exists():
        return dest
    img = Image.new("RGB", (size, size), "#e8e8e8")
    d = ImageDraw.Draw(img)
    half = size // 2
    panes = [
        ((0, 0), "FRONT", "#4a7fb5"),
        ((half, 0), "LEFT", "#5ca86e"),
        ((0, half), "BACK", "#b5684a"),
        ((half, half), "RIGHT", "#9a6ab5"),
    ]
    for (x, y), label, color in panes:
        # a "figure": body + head silhouette, different per pane
        cx, cy = x + half // 2, y + half // 2
        d.ellipse([cx - 60, cy - 150, cx + 60, cy - 30], fill=color)
        d.rectangle([cx - 80, cy - 30, cx + 80, cy + 150], fill=color)
        d.text((x + 20, y + 12), label, fill="#333333")
        d.rectangle([x, y, x + half - 1, y + half - 1], outline="#999999")
    img.save(dest)
    return dest


def cube_glb() -> Path:
    """Build a minimal valid GLB: one mesh, 8 verts, 12 tris, base color."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    dest = FIXTURE_DIR / "cube.glb"
    if dest.exists():
        return dest

    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
        (1, 2, 6), (1, 6, 5), (3, 0, 4), (3, 4, 7),
    ]
    vbytes = b"".join(struct.pack("<fff", *v) for v in verts)
    ibytes = b"".join(struct.pack("<HHH", *t) for t in tris)
    if len(ibytes) % 4:
        ibytes += b"\x00" * (4 - len(ibytes) % 4)
    bin_chunk = vbytes + ibytes

    gltf = {
        "asset": {"version": "2.0", "generator": "orrery-fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "cube"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.29, 0.5, 0.71, 1.0],
                "metallicFactor": 0.1, "roughnessFactor": 0.8,
            },
            "name": "fixture",
        }],
        "buffers": [{"byteLength": len(bin_chunk)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vbytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(vbytes), "byteLength": len(tris) * 6, "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
             "min": [-0.5, -0.5, -0.5], "max": [0.5, 0.5, 0.5]},
            {"bufferView": 1, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"},
        ],
    }
    jbytes = json.dumps(gltf, separators=(",", ":")).encode()
    if len(jbytes) % 4:
        jbytes += b" " * (4 - len(jbytes) % 4)

    total = 12 + 8 + len(jbytes) + 8 + len(bin_chunk)
    out = b"glTF" + struct.pack("<II", 2, total)
    out += struct.pack("<I", len(jbytes)) + b"JSON" + jbytes
    out += struct.pack("<I", len(bin_chunk)) + b"BIN\x00" + bin_chunk
    dest.write_bytes(out)
    return dest


def render_image() -> Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    dest = FIXTURE_DIR / "render.png"
    if dest.exists():
        return dest
    img = Image.new("RGB", (512, 512), "#2a2a30")
    d = ImageDraw.Draw(img)
    d.polygon([(256, 120), (380, 200), (380, 340), (256, 420), (132, 340), (132, 200)], fill="#4a7fb5")
    d.text((20, 20), "mock render", fill="#cccccc")
    img.save(dest)
    return dest
