"""Unit tests: splitter geometry, tripo option validation, engine resume."""
import asyncio
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MOCK_APIS", "1")


# ---------- splitter ----------

def test_split_grid_maps_panes_to_views(tmp_path):
    from app.services.splitter import split_grid
    # 2x2 grid with a distinct color per pane (matching GRID_LAYOUT)
    img = Image.new("RGB", (400, 400))
    colors = {(0, 0): (255, 0, 0), (1, 0): (0, 255, 0), (0, 1): (0, 0, 255), (1, 1): (255, 255, 0)}
    for (c, r), col in colors.items():
        for x in range(c * 200, (c + 1) * 200):
            for y in range(r * 200, (r + 1) * 200):
                img.putpixel((x, y), col)
    src = tmp_path / "grid.png"
    img.save(src)

    out = split_grid(src, tmp_path / "views")
    assert set(out) == {"front", "left", "back", "right"}
    # front = TL = red; right = BR = yellow
    assert Image.open(out["front"]).getpixel((100, 100)) == (255, 0, 0)
    assert Image.open(out["left"]).getpixel((100, 100)) == (0, 255, 0)
    assert Image.open(out["back"]).getpixel((100, 100)) == (0, 0, 255)
    assert Image.open(out["right"]).getpixel((100, 100)) == (255, 255, 0)


def test_split_grid_custom_mapping(tmp_path):
    from app.services.splitter import split_grid
    img = Image.new("RGB", (200, 200), (10, 10, 10))
    for x in range(100):
        for y in range(100):
            img.putpixel((x, y), (200, 0, 0))  # TL red
    src = tmp_path / "g.png"
    img.save(src)
    # user swaps: TL pane is actually the back view
    out = split_grid(src, tmp_path / "v", mapping={"back": (0, 0), "front": (1, 1)})
    assert set(out) == {"back", "front"}
    assert Image.open(out["back"]).getpixel((50, 50)) == (200, 0, 0)


# ---------- option validation ----------

def test_mesh_options_v25_strips_v30_params():
    from app.pipeline.tripo_options import clean_mesh_options
    out = clean_mesh_options({"model": "v2.5-20250123", "quad": True,
                              "texture_quality": "detailed", "smart_low_poly": True,
                              "face_limit": 100000})
    assert out["model"] == "v2.5-20250123"
    assert "quad" not in out and "texture_quality" not in out and "smart_low_poly" not in out
    assert out["face_limit"] == 100000  # face_limit is fine on v2.5


def test_mesh_options_v31_keeps_v30_params():
    from app.pipeline.tripo_options import clean_mesh_options
    out = clean_mesh_options({"model": "v3.1-20260211", "quad": True,
                              "texture_quality": "extreme", "geometry_quality": "detailed"})
    assert out["quad"] is True
    assert out["texture_quality"] == "extreme"
    assert out["geometry_quality"] == "detailed"


def test_mesh_options_p1_allowlist():
    from app.pipeline.tripo_options import clean_mesh_options
    out = clean_mesh_options({"model": "P1-20260311", "quad": True,
                              "generate_parts": True, "face_limit": 5000, "pbr": True})
    assert "quad" not in out and "generate_parts" not in out
    assert out["face_limit"] == 5000 and out["texture"] is True


def test_mesh_options_generate_parts_conflicts():
    from app.pipeline.tripo_options import clean_mesh_options
    out = clean_mesh_options({"model": "v3.1-20260211", "generate_parts": True,
                              "pbr": True, "quad": True})
    assert out["generate_parts"] is True
    assert out.get("texture") is False and "pbr" not in out and "quad" not in out


def test_mesh_options_unknown_model():
    from app.pipeline.tripo_options import clean_mesh_options
    with pytest.raises(ValueError):
        clean_mesh_options({"model": "v9.9-fake"})


def test_generic_options_enum_guard():
    from app.pipeline.tripo_options import clean_generic_options
    with pytest.raises(ValueError):
        clean_generic_options("retopo", {"model": "v3.0"})  # not a valid decimate model
    out = clean_generic_options("retopo", {"model": "v2.0", "face_limit": 5000, "quad": True})
    assert out == {"model": "v2.0", "face_limit": 5000, "quad": True, "bake": True}


# ---------- engine resume ----------

@pytest.mark.asyncio
async def test_engine_resume_reattaches_nodes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MOCK_APIS", "1")
    # fresh module state
    from tests.conftest import reset_app_modules
    reset_app_modules()
    from app.config import get_settings
    get_settings.cache_clear()
    from app.db import init_db, session_scope
    from app.models import Node, NodeStatus, OpType, Project
    from app.pipeline.engine import Engine

    await init_db()
    async with session_scope() as s:
        p = Project(name="t", prompt="a cube")
        s.add(p)
        await s.commit()
        # simulate a node that was mid-flight when the server died
        n = Node(project_id=p.id, parent_id=None, op_type=OpType.image_gen,
                 options={}, status=NodeStatus.running, provider="wavespeed",
                 provider_task_id="mock-resume-1")
        s.add(n)
        await s.commit()
        node_id = n.id

    eng = Engine()
    await eng.resume_all()
    for _ in range(60):
        node = await eng.get_node(node_id)
        if node.status == NodeStatus.completed:
            break
        await asyncio.sleep(0.2)
    assert node.status == NodeStatus.completed
    assets = await eng.node_assets(node_id)
    assert any(a.kind == "grid" for a in assets)


# ---------- prompt assembly ----------

def test_assemble_prompt_variants():
    from app.pipeline.prompts import assemble_prompt, CHARACTER_SUFFIX, GRID_CONTRACT
    # plain: subject + contract only
    p = assemble_prompt("a mug", {})
    assert p.startswith("a mug") and GRID_CONTRACT in p and CHARACTER_SUFFIX not in p
    # character checkbox on: suffix inserted before contract
    p = assemble_prompt("a fox", {"character": True})
    assert CHARACTER_SUFFIX in p and p.index(CHARACTER_SUFFIX) < p.index(GRID_CONTRACT)
    # custom suffix + custom contract
    p = assemble_prompt("a fox", {"character": True, "character_suffix": "A-POSE!", "contract": "MY GRID"})
    assert "A-POSE!" in p and "MY GRID" in p and CHARACTER_SUFFIX not in p
    # no grid contract (raw prompt for image_edit)
    p = assemble_prompt("golden armor", {"grid_contract": False})
    assert p == "golden armor"


# ---------- image model registry ----------

def test_image_model_mappers():
    from app.pipeline.image_models import IMAGE_MODELS, _dims, model_entry
    o = {"_prompt": "P", "resolution": "4k", "aspect_ratio": "16:9", "quality": "high"}

    # gpt-image-2: edit vs t2i endpoints + cost table
    ep, body, cost = IMAGE_MODELS["gpt-image-2 @wavespeed"]["ws_request"](o, ["u1", "u2"], False)
    assert ep.endswith("/edit") and body["images"] == ["u1", "u2"] and cost == 0.73 + 0.012

    # gemini pro: no quality key, 4k price
    ep, body, cost = IMAGE_MODELS["gemini-3-pro @wavespeed"]["ws_request"](o, [], False)
    assert ep == "google/nano-banana-pro/text-to-image" and "quality" not in body and cost == 0.24

    # flux on wavespeed: pixel size string, 4MP cap for 16:9 at "4k"
    ep, body, _ = IMAGE_MODELS["flux-2-max @wavespeed"]["ws_request"](o, [], False)
    w, h = map(int, body["size"].split("*"))
    assert ep.endswith("text-to-image") and w * h <= 4_200_000 and abs(w / h - 16 / 9) < 0.1

    # luma edit mode: image + reference split
    ep, body, _ = IMAGE_MODELS["luma-uni-1 @wavespeed"]["ws_request"](o, ["a", "b", "c"], True)
    assert ep == "luma/uni-v1/edit" and body["image"] == "a" and body["reference"] == ["b", "c"]

    # grok: resolution mapping caps at 2K
    p = IMAGE_MODELS["grok-imagine-quality @openrouter"]["map_options"]({"resolution": "4k"})
    assert p["resolution"] == "2K"
    p = IMAGE_MODELS["grok-imagine-quality @openrouter"]["map_options"]({"resolution": "1k"})
    assert p["resolution"] == "1K"

    # bfl: dims respect multiple-of-16 and MP cap
    kw = IMAGE_MODELS["flux-2-max @bfl"]["map_options"]({"resolution": "2k", "aspect_ratio": "1:1"})
    assert kw["width"] % 16 == 0 and kw["width"] * kw["height"] <= 4_200_000

    # unknown model raises
    import pytest as _pt
    with _pt.raises(ValueError):
        model_entry("dalle-9000")


# ---------- mesh dimensions + rescale ----------

def test_glb_bounds_and_rescale(tmp_path):
    from app.pipeline.meshinfo import glb_bounds, wrap_scale
    from app.clients.fixtures import cube_glb
    b = glb_bounds(cube_glb())
    assert b["size"] == [1.0, 1.0, 1.0] and b["largest"] == 1.0
    out = tmp_path / "scaled.glb"
    nb = wrap_scale(cube_glb(), out, 2.5)
    assert abs(nb["largest"] - 2.5) < 1e-4
    assert abs(glb_bounds(out)["largest"] - 2.5) < 1e-4  # re-read from disk matches


def _parts_glb(path, translations):
    """Minimal multi-part GLB: one unit cube per translation, each its own node /
    mesh / material / POSITION accessor — mirrors Tripo segment output."""
    import json as _json
    import struct as _struct
    from app.pipeline.meshinfo import write_glb
    verts = [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
             (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)]
    tris = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
            (2, 3, 7), (2, 7, 6), (1, 2, 6), (1, 6, 5), (3, 0, 4), (3, 4, 7)]
    vbytes = b"".join(_struct.pack("<fff", *v) for v in verts)
    ibytes = b"".join(_struct.pack("<HHH", *t) for t in tris)
    if len(ibytes) % 4:
        ibytes += b"\x00" * (4 - len(ibytes) % 4)
    per = vbytes + ibytes
    nodes, meshes, mats, bvs, accs, blob = [], [], [], [], [], b""
    for i, tr in enumerate(translations):
        base = len(blob)
        blob += per
        bvs.append({"buffer": 0, "byteOffset": base, "byteLength": len(vbytes), "target": 34962})
        bvs.append({"buffer": 0, "byteOffset": base + len(vbytes), "byteLength": len(tris) * 6, "target": 34963})
        accs.append({"bufferView": len(bvs) - 2, "componentType": 5126, "count": 8, "type": "VEC3",
                     "min": [-0.5, -0.5, -0.5], "max": [0.5, 0.5, 0.5]})
        accs.append({"bufferView": len(bvs) - 1, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"})
        meshes.append({"name": f"tripo_mesh_{i}",
                       "primitives": [{"attributes": {"POSITION": len(accs) - 2}, "indices": len(accs) - 1, "material": i}]})
        mats.append({"name": f"mat_{i}", "pbrMetallicRoughness": {"baseColorFactor": [i / 10, 0.5, 0.7, 1.0]}})
        nodes.append({"mesh": i, "name": f"tripo_part_{i}", "translation": list(tr)})
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
            "nodes": nodes, "meshes": meshes, "materials": mats,
            "buffers": [{"byteLength": len(blob)}], "bufferViews": bvs, "accessors": accs}
    write_glb(path, gltf, blob)
    return path


def test_glb_fuse_preserves_bounds_and_materials(tmp_path):
    from app.pipeline.meshinfo import glb_fuse, compute_bounds, read_glb
    src = _parts_glb(tmp_path / "seg.glb", [(0, 0, 0), (3, 0, 0), (0, 4, 0)])
    g0, _ = read_glb(src)
    before = compute_bounds(g0)
    assert before["size"] == [4.0, 5.0, 1.0]  # spans the 3 translated cubes (±0.5 each)

    out = tmp_path / "fused.glb"
    res = glb_fuse(src, out, [["tripo_part_0", "tripo_part_2"]])
    assert res["fused"] == 1
    # 3 parts -> 2 (part_0+part_2 merged; part_1 untouched)
    assert sorted(res["parts"]) == ["tripo_part_1", "tripo_part_fused_0"]
    # bounds unchanged: translation baked into vertices, not lost
    assert res["bounds"]["size"] == before["size"]
    assert abs(os.path.getsize(out) - os.path.getsize(src)) < 4096  # no buffer growth

    g1, _ = read_glb(out)
    fnode = next(n for n in g1["nodes"] if n.get("name") == "tripo_part_fused_0")
    assert "translation" not in fnode                       # baked away
    prims = g1["meshes"][fnode["mesh"]]["primitives"]
    assert len(prims) == 2                                  # both parts' geometry
    assert {p["material"] for p in prims} == {0, 2}         # both materials preserved


def test_glb_fuse_rejects_singletons(tmp_path):
    from app.pipeline.meshinfo import glb_fuse
    src = _parts_glb(tmp_path / "seg.glb", [(0, 0, 0), (3, 0, 0)])
    res = glb_fuse(src, tmp_path / "o.glb", [["tripo_part_0"]])  # group of 1 = no-op
    assert res["fused"] == 0


def test_rescale_target_size_math(tmp_path):
    from app.pipeline.meshinfo import glb_bounds, wrap_scale
    from app.clients.fixtures import cube_glb
    cur = glb_bounds(cube_glb())["largest"]
    out = tmp_path / "s.glb"
    wrap_scale(cube_glb(), out, 1.7 / cur)  # target largest = 1.7
    assert abs(glb_bounds(out)["largest"] - 1.7) < 1e-4
