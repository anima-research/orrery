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

def _read_positions(gltf: dict, bin_chunk: bytes, accessor_idx: int) -> list[tuple[float, float, float]]:
    acc = gltf["accessors"][accessor_idx]
    bv = gltf["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or 12
    n = acc["count"]
    out = []
    for i in range(n):
        off = base + i * stride
        out.append(struct.unpack_from("<fff", bin_chunk, off))
    return out


def glb_fuse(src: Path, dst: Path, groups: list[list[str]]) -> dict:
    """Merge each group of named parts into one part. Each part node's translation
    is baked into its POSITION data *in place* (Tripo parts are translation-only
    with their own un-shared, un-interleaved POSITION accessor), so geometry and
    per-part materials are preserved exactly, the buffer never grows, and no Tripo
    round-trip is needed. Parts not in any group are left untouched.
    Returns {parts, fused, bounds}."""
    gltf, bin_chunk = read_glb(src)
    nodes = gltf["nodes"]
    meshes = gltf.setdefault("meshes", [])
    accessors = gltf["accessors"]
    buffer_views = gltf["bufferViews"]
    scene = gltf["scenes"][gltf.get("scene", 0)]
    new_bin = bytearray(bin_chunk)

    # part identifier -> node index (node name, then mesh name)
    name2node: dict[str, int] = {}
    for i, n in enumerate(nodes):
        if n.get("name"):
            name2node.setdefault(n["name"], i)
        if n.get("mesh") is not None:
            mn = meshes[n["mesh"]].get("name")
            if mn:
                name2node.setdefault(mn, i)

    # child -> parent index, so a merged node is detached from wherever it actually
    # hangs (a scene root, or a child of a wrapper e.g. rescale's orrery_scale node,
    # or an armature) — not only from scene["nodes"].
    parent_of: dict[int, int] = {}
    for pi, n in enumerate(nodes):
        for c in n.get("children", []):
            parent_of[c] = pi

    def detach(m: int) -> None:
        pi = parent_of.get(m)
        if pi is not None:
            kids = nodes[pi].get("children")
            if kids and m in kids:
                kids.remove(m)
        elif m in scene.get("nodes", []):
            scene["nodes"].remove(m)

    def bake_in_place(acc_idx: int, offset: tuple[float, float, float]) -> None:
        """Add offset to every vertex of a tightly-packed VEC3/float POSITION
        accessor, writing back into new_bin and refreshing the accessor min/max."""
        acc = accessors[acc_idx]
        bv = buffer_views[acc["bufferView"]]
        base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = bv.get("byteStride") or 12
        ox, oy, oz = offset
        lo = [math.inf, math.inf, math.inf]
        hi = [-math.inf, -math.inf, -math.inf]
        for i in range(acc["count"]):
            off = base + i * stride
            x, y, z = struct.unpack_from("<fff", new_bin, off)
            x, y, z = x + ox, y + oy, z + oz
            struct.pack_into("<fff", new_bin, off, x, y, z)
            lo[0] = min(lo[0], x); hi[0] = max(hi[0], x)
            lo[1] = min(lo[1], y); hi[1] = max(hi[1], y)
            lo[2] = min(lo[2], z); hi[2] = max(hi[2], z)
        acc["min"], acc["max"] = lo, hi

    fused = 0
    used: set[int] = set()   # nodes already consumed by an earlier group
    baked: set[int] = set()  # accessors already offset (never bake twice)
    for gi, group in enumerate(groups):
        member_idxs: list[int] = []
        for nm in group:
            idx = name2node.get(nm)
            if idx is not None and idx not in member_idxs and idx not in used:
                member_idxs.append(idx)
        if len(member_idxs) < 2:
            continue  # nothing to merge
        used.update(member_idxs)
        new_prims = []
        for m in member_idxs:
            node = nodes[m]
            tr = node.get("translation", [0, 0, 0])
            for prim in meshes[node["mesh"]].get("primitives", []):
                pos_acc = prim.get("attributes", {}).get("POSITION")
                if pos_acc is not None and tr != [0, 0, 0] and pos_acc not in baked:
                    bake_in_place(pos_acc, (tr[0], tr[1], tr[2]))
                    baked.add(pos_acc)
                new_prims.append(prim)
        # repurpose the first member as the fused node; drop the rest from the scene
        target = member_idxs[0]
        meshes.append({"name": f"tripo_mesh_fused_{gi}", "primitives": new_prims})
        nodes[target]["mesh"] = len(meshes) - 1
        nodes[target]["name"] = f"tripo_part_fused_{gi}"
        nodes[target].pop("translation", None)  # baked into vertices
        for m in member_idxs[1:]:
            detach(m)
        fused += 1

    write_glb(dst, gltf, bytes(new_bin))
    # remaining part names: every still-referenced node that carries a mesh (parts
    # can live under a wrapper, so walk the scene graph, not just scene["nodes"])
    reachable: list[int] = []
    seen: set[int] = set()
    stack = list(scene.get("nodes", []))
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        reachable.append(i)
        stack.extend(nodes[i].get("children", []))
    parts = [nodes[i].get("name") for i in reachable
             if nodes[i].get("mesh") is not None and nodes[i].get("name")]
    return {"parts": parts, "fused": fused, "bounds": compute_bounds(gltf)}


def glb_drop(src: Path, dst: Path, parts: list[str]) -> dict:
    """Delete named parts from the mesh — the counterpart to glb_fuse for the
    'floating junk piece after segmentation' case. Each named node (or the node
    carrying a mesh of that name) is detached from wherever it hangs, along with
    its whole subtree. Bytes stay in the buffer (dropped geometry becomes
    unreferenced padding — cheap, and the store diet reclaims it later); what
    matters is the scene graph no longer reaches it.
    Returns {parts, dropped, bounds}."""
    gltf, bin_chunk = read_glb(src)
    nodes = gltf["nodes"]
    meshes = gltf.get("meshes", [])
    scene = gltf["scenes"][gltf.get("scene", 0)]

    name2node: dict[str, int] = {}
    for i, n in enumerate(nodes):
        if n.get("name"):
            name2node.setdefault(n["name"], i)
        if n.get("mesh") is not None:
            mn = meshes[n["mesh"]].get("name")
            if mn:
                name2node.setdefault(mn, i)

    parent_of: dict[int, int] = {}
    for pi, n in enumerate(nodes):
        for c in n.get("children", []):
            parent_of[c] = pi

    dropped = 0
    for nm in parts:
        idx = name2node.get(nm)
        if idx is None:
            continue
        pi = parent_of.get(idx)
        if pi is not None:
            kids = nodes[pi].get("children")
            if kids and idx in kids:
                kids.remove(idx)
                dropped += 1
        elif idx in scene.get("nodes", []):
            scene["nodes"].remove(idx)
            dropped += 1

    write_glb(dst, gltf, bin_chunk)
    # remaining part names — same scene-graph walk as glb_fuse
    reachable: list[int] = []
    seen: set[int] = set()
    stack = list(scene.get("nodes", []))
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        reachable.append(i)
        stack.extend(nodes[i].get("children", []))
    remaining = [nodes[i].get("name") for i in reachable
                 if nodes[i].get("mesh") is not None and nodes[i].get("name")]
    return {"parts": remaining, "dropped": dropped, "bounds": compute_bounds(gltf)}


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
