"""GLB geometry inspection + local rescale — no provider round-trip.

Absolute mesh dimensions come from accessor min/max (POSITION accessors carry
them per spec) transformed by the node hierarchy, so we never read vertex data.
Rescale wraps the scene under one scale node — uniform, skin-safe, instant, free.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any


# ---------- GLB read/write ----------

def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("not a GLB container")
    _, _, total = struct.unpack("<4sII", data[:12])
    off, gltf, bin_chunk = 12, None, b""
    while off < total:
        clen, ctype = struct.unpack("<I4s", data[off:off + 8])
        body = data[off + 8:off + 8 + clen]
        if ctype == b"JSON":
            gltf = json.loads(body)
        elif ctype == b"BIN\x00":
            bin_chunk = body
        off += 8 + clen
    if gltf is None:
        raise ValueError("GLB has no JSON chunk")
    return gltf, bin_chunk


def write_glb(path: Path, gltf: dict, bin_chunk: bytes) -> None:
    jbytes = json.dumps(gltf, separators=(",", ":")).encode()
    if len(jbytes) % 4:
        jbytes += b" " * (4 - len(jbytes) % 4)
    bin_pad = bin_chunk
    if len(bin_pad) % 4:
        bin_pad += b"\x00" * (4 - len(bin_pad) % 4)
    total = 12 + 8 + len(jbytes) + (8 + len(bin_pad) if bin_pad else 0)
    out = b"glTF" + struct.pack("<II", 2, total)
    out += struct.pack("<I", len(jbytes)) + b"JSON" + jbytes
    if bin_pad:
        out += struct.pack("<I", len(bin_pad)) + b"BIN\x00" + bin_pad
    path.write_bytes(out)


# ---------- matrix helpers (column-major, glTF convention) ----------

def _identity() -> list[float]:
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _mul(a: list[float], b: list[float]) -> list[float]:
    r = [0.0] * 16
    for c in range(4):
        for row in range(4):
            r[c * 4 + row] = sum(a[k * 4 + row] * b[c * 4 + k] for k in range(4))
    return r


def _trs_matrix(node: dict) -> list[float]:
    if "matrix" in node:
        return list(node["matrix"])
    t = node.get("translation", [0, 0, 0])
    q = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    x, y, z, w = q
    # rotation matrix from quaternion
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    r = [
        1 - 2 * (yy + zz), 2 * (xy + wz), 2 * (xz - wy), 0,
        2 * (xy - wz), 1 - 2 * (xx + zz), 2 * (yz + wx), 0,
        2 * (xz + wy), 2 * (yz - wx), 1 - 2 * (xx + yy), 0,
        0, 0, 0, 1,
    ]
    sm = [s[0], 0, 0, 0, 0, s[1], 0, 0, 0, 0, s[2], 0, 0, 0, 0, 1]
    tm = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, t[0], t[1], t[2], 1]
    return _mul(tm, _mul(r, sm))


def _xform(m: list[float], p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


# ---------- bounds ----------

def compute_bounds(gltf: dict) -> dict | None:
    """World-space axis-aligned bounds of the default scene. Returns
    {size:[x,y,z], min, max, largest} in the model's own units, or None."""
    accessors = gltf.get("accessors", [])
    meshes = gltf.get("meshes", [])
    nodes = gltf.get("nodes", [])
    scene_idx = gltf.get("scene", 0)
    scenes = gltf.get("scenes", [{"nodes": list(range(len(nodes)))}])
    roots = scenes[scene_idx].get("nodes", []) if scenes else list(range(len(nodes)))

    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]

    def visit(ni: int, parent_m: list[float]) -> None:
        node = nodes[ni]
        m = _mul(parent_m, _trs_matrix(node))
        if node.get("mesh") is not None:
            for prim in meshes[node["mesh"]].get("primitives", []):
                ai = prim.get("attributes", {}).get("POSITION")
                if ai is None:
                    continue
                acc = accessors[ai]
                amin, amax = acc.get("min"), acc.get("max")
                if not amin or not amax:
                    continue
                # transform all 8 corners of the local AABB
                for cx in (amin[0], amax[0]):
                    for cy in (amin[1], amax[1]):
                        for cz in (amin[2], amax[2]):
                            wx, wy, wz = _xform(m, (cx, cy, cz))
                            lo[0] = min(lo[0], wx); hi[0] = max(hi[0], wx)
                            lo[1] = min(lo[1], wy); hi[1] = max(hi[1], wy)
                            lo[2] = min(lo[2], wz); hi[2] = max(hi[2], wz)
        for c in node.get("children", []):
            visit(c, m)

    for r in roots:
        visit(r, _identity())

    if not all(math.isfinite(v) for v in lo + hi):
        return None
    size = [round(hi[i] - lo[i], 5) for i in range(3)]
    return {
        "size": size,
        "min": [round(v, 5) for v in lo],
        "max": [round(v, 5) for v in hi],
        "largest": round(max(size), 5),
    }


def glb_bounds(path: Path) -> dict | None:
    try:
        gltf, _ = read_glb(path)
        return compute_bounds(gltf)
    except Exception:
        return None


# ---------- rescale ----------

def wrap_scale(src: Path, dst: Path, factor: float) -> dict:
    """Bake a uniform scale by wrapping the scene under one scale node.
    Skin-safe (bones scale with the mesh). Returns the new bounds."""
    gltf, bin_chunk = read_glb(src)
    nodes = gltf.setdefault("nodes", [])
    scene_idx = gltf.get("scene", 0)
    scenes = gltf.setdefault("scenes", [{"nodes": list(range(len(nodes)))}])
    roots = scenes[scene_idx].get("nodes", list(range(len(nodes))))
    wrapper = {"name": "orrery_scale", "scale": [factor, factor, factor], "children": list(roots)}
    nodes.append(wrapper)
    scenes[scene_idx]["nodes"] = [len(nodes) - 1]
    write_glb(dst, gltf, bin_chunk)
    b = compute_bounds(gltf)
    return b or {}
