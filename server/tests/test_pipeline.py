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
        clean_generic_options("retopo", {"model": "v9.0"})  # not a valid decimate model
    out = clean_generic_options("retopo", {"model": "v2.0", "face_limit": 5000, "quad": True})
    # smart_uv is per_model-hidden on v2.0: Tripo 1004s it there, so never sent
    assert out == {"model": "v2.0", "face_limit": 5000, "quad": True, "bake": True}


# ---------- 2026-10 features: retopo v3.0, smart UV, texture v3.5, rig v3.0 ----------

def test_retopo_v3_default_and_smart_uv():
    from app.pipeline.tripo_options import clean_generic_options
    out = clean_generic_options("retopo", {})
    assert out == {"model": "v3.0", "face_limit": 10000, "quad": False,
                   "smart_uv": True, "bake": True}
    # v1.0 takes neither bake nor part_names nor smart_uv
    out = clean_generic_options("retopo", {"model": "v1.0", "smart_uv": True, "bake": True,
                                           "part_names": ["tripo_part_0"], "face_limit": 3000})
    assert out == {"model": "v1.0", "face_limit": 3000, "quad": False}
    # v2.0 keeps part_names
    out = clean_generic_options("retopo", {"model": "v2.0", "part_names": ["a"]})
    assert out["part_names"] == ["a"] and "smart_uv" not in out


def test_retopo_v3_face_limits_match_live_api():
    """Ranges verified live 2026-10-21: 499/20001 tri and 10001 quad are 1004."""
    from app.pipeline.tripo_options import clean_generic_options
    for bad in (499, 20001):
        with pytest.raises(ValueError, match="500-20000"):
            clean_generic_options("retopo", {"model": "v3.0", "face_limit": bad})
    with pytest.raises(ValueError, match="500-10000 with quad"):
        clean_generic_options("retopo", {"model": "v3.0", "face_limit": 10001, "quad": True})
    assert clean_generic_options("retopo", {"model": "v3.0", "face_limit": 20000})["face_limit"] == 20000
    # empty = adaptive on v3.0
    out = clean_generic_options("retopo", {"model": "v3.0", "face_limit": None})
    assert "face_limit" not in out
    # v2.0 keeps its wide range
    assert clean_generic_options("retopo", {"model": "v2.0", "face_limit": 100000})["face_limit"] == 100000


def test_texture_op_v35_fast_and_delight():
    from app.pipeline.tripo_options import clean_generic_options
    out = clean_generic_options("texture", {"model": "v3.5-20260815", "texture_quality": "fast"})
    assert out["texture_quality"] == "fast" and out["delight"] is True
    out = clean_generic_options("texture", {"model": "v3.0-20250812", "delight": False})
    assert "delight" not in out           # only v3.5 reads it
    with pytest.raises(ValueError, match="fast"):
        clean_generic_options("texture", {"model": "v3.0-20250812", "texture_quality": "fast"})


def test_mesh_texture_version():
    from app.pipeline.tripo_options import clean_mesh_options
    # default: Tripo derives the texture model, no v3.5-only fields leak
    out = clean_mesh_options({"model": "v3.1-20260211"})
    assert "texture_version" not in out and "delight" not in out
    # fast pins v3.5 when no version was chosen
    out = clean_mesh_options({"model": "v3.1-20260211", "texture_quality": "fast"})
    assert out["texture_version"] == "v3.5-20260815" and out["delight"] is True
    # explicit non-3.5 + fast is refused (Tripo would 1004)
    with pytest.raises(ValueError, match="fast"):
        clean_mesh_options({"model": "v3.1-20260211", "texture_quality": "fast",
                            "texture_version": "v3.0-20250812"})
    # P-series takes texture_version too
    out = clean_mesh_options({"model": "P2-20260801", "texture_version": "v3.5-20260815",
                              "delight": False})
    assert out["texture_version"] == "v3.5-20260815" and out["delight"] is False
    # untextured parts: texture fields are dropped
    out = clean_mesh_options({"model": "v3.1-20260211", "generate_parts": True,
                              "texture_version": "v3.5-20260815", "texture_quality": "fast"})
    assert "texture_version" not in out and "delight" not in out
    assert out.get("texture_quality") != "fast"


def test_rig_model_resolution():
    from app.pipeline.tripo_options import resolve_rig_model
    assert resolve_rig_model("auto", "biped", "tripo") == "v3.0-20260909"
    assert resolve_rig_model(None, "quadruped", None) == "v3.0-20260909"
    assert resolve_rig_model("auto", "biped", "vrm") == "v3.0-20260909"
    assert resolve_rig_model("v1.0-20240301", "biped", "mixamo") == "v1.0-20240301"
    assert resolve_rig_model("v2.5-20260210", "avian", "tripo") == "v2.5-20260210"
    # Tripo ACCEPTS these at creation (verified live) — we must refuse them
    with pytest.raises(ValueError, match="needs rig model"):
        resolve_rig_model("v1.0-20240301", "biped", "vrm")
    with pytest.raises(ValueError, match="needs rig model"):
        resolve_rig_model("v2.5-20260210", "biped", "unreal")
    with pytest.raises(ValueError, match="others"):
        resolve_rig_model("v1.0-20240301", "others", None)
    with pytest.raises(ValueError, match="biped-only"):
        resolve_rig_model("v1.0-20240301", "avian", None)


def test_rig_spec_per_model_enum():
    from app.pipeline.tripo_options import clean_generic_options
    assert clean_generic_options("rig", {"model": "auto", "spec": "unreal"})["spec"] == "unreal"
    with pytest.raises(ValueError, match="v1.0-20240301"):
        clean_generic_options("rig", {"model": "v1.0-20240301", "spec": "vrm"})


def test_rig_version_of_legacy_nodes():
    from app.pipeline.tripo_options import rig_version_of
    assert rig_version_of({"model_resolved": "v3.0-20260909", "model": "auto"}) == "v3.0-20260909"
    assert rig_version_of({"model": "v2.5-20260210"}) == "v2.5-20260210"
    # pre-2026-10 auto rule: biped -> v1.0, everything else -> v2.5
    assert rig_version_of({"model": "auto", "rig_type": "biped"}) == "v1.0-20240301"
    assert rig_version_of({"model": "auto", "rig_type": "auto",
                           "rig_type_resolved": "octopod"}) == "v2.5-20260210"
    assert rig_version_of({"rig_type": "auto"}) is None


def test_retarget_presets_translate_and_validate():
    from app.pipeline.tripo_options import resolve_retarget_animations as r
    v1, v25, v3 = "v1.0-20240301", "v2.5-20260210", "v3.0-20260909"
    assert r(None, v3) == ["preset:idle"]
    assert r(None, v1) == ["preset:biped:idle"]
    # v3.0 plays both libraries as-is (verified live 2026-10-21)
    assert r(["preset:biped:dance_01", "preset:run"], v3) == ["preset:biped:dance_01",
                                                               "preset:run"]
    # v2.5 only knows the short list: translate the v1.0 spelling
    assert r(["preset:biped:walk", "preset:run"], v25) == ["preset:walk", "preset:run"]
    # v1.0 only knows preset:biped:*
    assert r(["preset:walk", "preset:biped:dance_01"], v1) == ["preset:biped:walk",
                                                                "preset:biped:dance_01"]
    assert r("preset:jump", v3) == ["preset:jump"]
    assert r(["preset:quadruped:walk"], v3) == ["preset:quadruped:walk"]
    # no equivalent: refuse with the valid list + the rig hint
    with pytest.raises(ValueError, match="preset:idle.*rig made with model v3.0"):
        r(["preset:biped:dance_01"], v25)
    with pytest.raises(ValueError, match="not a preset"):
        r(["preset:__zzz_sentinel__"], v1)
    with pytest.raises(ValueError, match="not a preset"):
        r(["preset:biped:attack"], v3)   # a real prod guess — in neither library
    with pytest.raises(ValueError, match="at most 5"):
        r([f"preset:biped:{a}" for a in ("idle", "walk", "run", "jump", "fall", "turn")], v1)
    # unknown lineage (not a rig node): pass through untouched
    assert r(["preset:whatever"], None) == ["preset:whatever"]


def test_glb_triangle_count():
    from app.clients.fixtures import cube_glb
    from app.pipeline.meshinfo import glb_triangle_count
    assert glb_triangle_count(cube_glb()) == 12
    assert glb_triangle_count(Path(__file__)) is None


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


def test_openai_direct_models():
    from app.clients.openai_images import cost_from_usage
    from app.pipeline.image_models import DEFAULT_IMAGE_MODEL, IMAGE_MODELS, model_entry

    # 2.5 sunburst is the default; flare + gpt-image-2 direct are siblings; the
    # WaveSpeed relay stays and old "gpt-image-2" option values still mean it
    assert DEFAULT_IMAGE_MODEL == "gpt-image-2.5-sunburst @openai"
    for k in ("gpt-image-2.5-flare @openai", "gpt-image-2.5-sunburst @openai", "gpt-image-2 @openai"):
        e = IMAGE_MODELS[k]
        assert e["provider"] == "openai" and e["max_refs"] == 16 and e["path"] == k.split(" @")[0]
    assert model_entry("gpt-image-2") is IMAGE_MODELS["gpt-image-2 @wavespeed"]
    assert model_entry("gpt-image-2.5") is IMAGE_MODELS[DEFAULT_IMAGE_MODEL]

    # size = WxH, %16, inside the live-verified limits (3840 edge, 8,294,400 px
    # budget) for EVERY tier x aspect; quality passthrough; no input_fidelity.
    # 1:1 and 16:9 "4k" both sit EXACTLY on the budget (live-verified to pass)
    m = IMAGE_MODELS[DEFAULT_IMAGE_MODEL]["map_options"]
    p = m({"resolution": "4k", "aspect_ratio": "1:1", "quality": "low"})
    assert p == {"size": "2880x2880", "quality": "low"}
    assert m({"resolution": "4k", "aspect_ratio": "16:9"})["size"] == "3840x2160"
    p = m({"resolution": "2k", "aspect_ratio": "16:9"})
    w, h = map(int, p["size"].split("x"))
    assert w == 2048 and h % 16 == 0 and abs(w / h - 16 / 9) < 0.05 and p["quality"] == "high"
    assert m({"resolution": "0.5k"})["size"] == "512x512"
    for res in ("0.5k", "1k", "2k", "4k"):
        for ar in ("1:1", "3:2", "2:3", "16:9", "9:16"):
            w, h = map(int, m({"resolution": res, "aspect_ratio": ar})["size"].split("x"))
            assert w % 16 == 0 and h % 16 == 0 and max(w, h) <= 3840 and w * h <= 3840 * 2160, (res, ar, w, h)

    # exact-usage cost: 20 text + 1000 image in, 229 out @ $5/$8/$30 per M
    usage = {"input_tokens": 1020, "output_tokens": 229,
             "input_tokens_details": {"text_tokens": 20, "image_tokens": 1000}}
    assert cost_from_usage("gpt-image-2.5-flare", usage) == round((20 * 5 + 1000 * 8 + 229 * 30) / 1e6, 4)
    assert cost_from_usage("gpt-image-2.5-flare", None) == 0.0


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


def test_glb_fuse_under_wrapper_removes_merged_nodes(tmp_path):
    """Parts nested under a wrapper (as rescale's orrery_scale produces) must still
    be detached on fuse — regression for fusing 3-of-4 yielding *more* parts."""
    from app.pipeline.meshinfo import glb_fuse, wrap_scale, read_glb
    flat = _parts_glb(tmp_path / "seg.glb", [(0, 0, 0), (3, 0, 0), (0, 4, 0), (0, 0, 5)])
    wrapped = tmp_path / "rescaled.glb"
    wrap_scale(flat, wrapped, 2.0)  # nests the 4 parts under one scale node

    out = tmp_path / "fused.glb"
    res = glb_fuse(wrapped, out, [["tripo_part_0", "tripo_part_1", "tripo_part_2"]])
    assert res["fused"] == 1
    # 4 parts, fuse 3 -> 2 (one fused + the untouched part_3), NOT 4+
    assert sorted(res["parts"]) == ["tripo_part_3", "tripo_part_fused_0"], res["parts"]

    # the merged member nodes are gone from the graph, not just orphaned in scene[]
    g, _ = read_glb(out)
    nodes = g["nodes"]
    reachable, stack = set(), list(g["scenes"][g.get("scene", 0)]["nodes"])
    while stack:
        i = stack.pop()
        if i in reachable:
            continue
        reachable.add(i)
        stack.extend(nodes[i].get("children", []))
    live = {nodes[i].get("name") for i in reachable if nodes[i].get("mesh") is not None}
    assert "tripo_part_1" not in live and "tripo_part_2" not in live
    assert live == {"tripo_part_3", "tripo_part_fused_0"}


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


# ---------- upload path-traversal hardening ----------

def test_safe_name_strips_traversal_and_absolute_paths():
    from app.pipeline.engine import Engine
    sn = Engine.safe_name
    # legit names pass through
    assert sn("photo.png", "ref.png") == "photo.png"
    assert sn("a/b/c.glb", "ref.png") == "c.glb"
    # absolute paths and traversal collapse to a bare basename
    assert sn("/etc/cron.d/pwn", "ref.png") == "pwn"
    assert sn("../../../../etc/passwd", "ref.png") == "passwd"
    assert sn("..\\..\\windows\\x.dll", "ref.png") == "x.dll"
    # empties / dot names / dotfiles fall back to the default
    for bad in ("", None, ".", "..", ".env"):
        assert sn(bad, "ref.png") == "ref.png"
    # result never contains a separator
    for name in ("/x", "../x", "a/b", "x\\y"):
        assert "/" not in sn(name, "ref.png")


def test_secure_dest_keeps_uploads_under_base(tmp_path):
    from app.pipeline.engine import engine
    base = tmp_path / "refs"
    base.mkdir()
    for evil in ("/etc/cron.d/pwn", "../../../../etc/passwd", "..\\..\\x"):
        dest = engine.secure_dest(base, evil, "ref.png")
        assert dest.parent == base.resolve()
