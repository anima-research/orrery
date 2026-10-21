"""Catalog of Tripo v3 options per op — single source of truth for
API payload validation AND the UI's option forms (served at /api/ops).

Each field: {type, enum?, default?, min?, max?, desc, requires_model_gte?}
Model ordering for gates: v2.5-20250123 < v3.0-20250812 < v3.1-20260211.
P1-20260311 / P2-20260801 are a separate low-poly family with their own allowlists
(P2 adds native quad + bigger budgets: 48-50000 tri / 48-25000 quad, API-verified
2026-08-25 via validator probes; unsupported params are silently ignored by Tripo,
quad is the one param it hard-rejects on non-P2 P-series).
"""
from __future__ import annotations

from typing import Any

from .image_models import DEFAULT_IMAGE_MODEL, IMAGE_MODELS
from .prompts import CHARACTER_SUFFIX, GRID_CONTRACT

_MODEL_NOTES = "; ".join(f"{k}: {v['notes']}" for k, v in IMAGE_MODELS.items())

MESH_MODELS = ["v3.1-20260211", "v3.0-20250812", "v2.5-20250123", "P2-20260801",
               "P1-20260311"]
_H_ORDER = {"v2.5-20250123": 0, "v3.0-20250812": 1, "v3.1-20260211": 2}

# Params only valid on H-series >= v3.0
V30_PLUS_PARAMS = {"texture_quality", "geometry_quality", "auto_size", "quad",
                   "smart_low_poly", "generate_parts", "compress"}
# Params supported by the P1 low-poly family
P1_ALLOWED = {"texture", "pbr", "texture_quality", "auto_size", "compress",
              "face_limit", "model_seed", "texture_seed", "orientation",
              "texture_alignment", "export_uv", "texture_version", "delight"}

# --- Texture model (2026-09) -------------------------------------------------
# v3.5 is reachable from models/texture (`model`) and from every generation
# endpoint (`texture_version`, independent of the geometry model). `fast` and
# `delight` exist ONLY on v3.5: Tripo answers `fast` on any other texture
# version with 1004 rather than downgrading, so we refuse it up front.
TEXTURE_V35 = "v3.5-20260815"
TEXTURE_VERSIONS = [TEXTURE_V35, "v3.0-20250812", "v2.5-20250123"]
TEXTURE_QUALITIES = ["fast", "standard", "detailed", "extreme"]

# --- Rigging (2026-10: rig v3.0) ---------------------------------------------
RIG_V3 = "v3.0-20260909"
RIG_V25 = "v2.5-20260210"
RIG_V1 = "v1.0-20240301"
RIG_MODELS = [RIG_V3, RIG_V25, RIG_V1]
RIG_TYPES = ["biped", "quadruped", "hexapod", "octopod", "avian", "serpentine",
             "aquatic", "others"]
# Engine skeleton presets: bone NAMING conventions, bipeds only, rig v3.0 only.
RIG_SPECS = ["tripo", "mixamo", "unreal", "unity", "vrm", "actorcore"]
RIG_V3_ONLY_SPECS = {"unreal", "unity", "vrm", "actorcore"}

# Retarget presets depend on the RIG version, not on retarget itself.
# Docs: v2.5 and v3.0 share one small library; v1.0 has its own 90+ biped
# library. Live (2026-10-21, new retarget algorithm): a v3.0 rig ALSO plays the
# v1.0 library — preset:biped:dance_01 came back as a distinct 23.2 s
# dance_01 clip, preset:biped:idle == preset:idle — so v3.0 gets both. A v2.5
# rig refused preset:biped:dance_01 ("Invalid input parameter").
_V1_BIPED = (
    "afraid agree angry_01 angry_02 angry_03 basketball_shot bow box_01 box_02 "
    "box_03 cast_a_spell cheer chop clap climb complain_01 complain_02 "
    "cross_body_crunch crossover_dribble cry dance_01 dance_02 dance_03 dance_04 "
    "dance_05 dance_06 defeat_02 defeat_03 depressed dig dive dribble fall fire "
    "flee_01 flee_02 flip fold_arms football_catch football_save football_pass "
    "freaky frightened front_kick_01 front_kick_02 frustrated_01 frustrated_02 "
    "golf greet_01 greet_02 greet_03 greet_04 heart_pose hit_to_body_01 "
    "hit_to_body_02 hit_to_head hit_to_side hit_to_stomach hug hurt idle "
    "jump_down jump jump_rope_01 jump_rope_02 laugh_01 laugh_02 lift_heavy "
    "look_around make_a_call_01 make_a_call_02 pitch_baseball play_mobile_game "
    "play_video_game press-up run_upstairs run scared_01 scared_02 scratch shoot "
    "shovel sing_01 sing_02 sing_03 sing_04 sit slash sob standing_relax surf "
    "swagger swim turn victory_celebration volleyball wait walk warm_up "
    "wave_goodbye_01 wave_goodbye_02").split()
_V25_BIPED = "idle walk run dive climb jump slash shoot hurt fall turn".split()
RETARGET_PRESETS: dict[str, list[str]] = {
    RIG_V1: [f"preset:biped:{a}" for a in _V1_BIPED],
    RIG_V25: [f"preset:{a}" for a in _V25_BIPED] + [
        "preset:quadruped:walk", "preset:hexapod:walk", "preset:octopod:walk",
        "preset:serpentine:march", "preset:aquatic:march"],
}
RETARGET_PRESETS[RIG_V3] = RETARGET_PRESETS[RIG_V25] + RETARGET_PRESETS[RIG_V1]
RETARGET_MAX_ANIMATIONS = 5

# --- Retopology (2026-10: retopo v3.0) -----------------------------------------
RETOPO_V3 = "v3.0"
RETOPO_V3_FACES = (500, 20_000)        # triangle output
RETOPO_V3_QUAD_MAX = 10_000            # quad output (a quad = one face)

# --- Smart UV (2026-10) ------------------------------------------------------
SMART_UV_MAX_TRIS = 80_000             # equivalent triangles (a quad counts as two)
# P2 (preview, 2026-08): everything P1 takes plus native quad topology.
P2_ALLOWED = P1_ALLOWED | {"quad"}

MESH_GEN_FIELDS: dict[str, dict[str, Any]] = {
    "model": {"type": "enum", "enum": MESH_MODELS, "default": "v3.1-20260211",
              "desc": "Tripo model version (P1/P2 = clean low-poly family; "
                      "P2 preview adds native quad + up to 50k faces)"},
    "texture": {"type": "bool", "default": True, "desc": "Generate texture"},
    "pbr": {"type": "bool", "default": True, "desc": "PBR maps (forces texture)"},
    "texture_quality": {"type": "enum", "enum": TEXTURE_QUALITIES,
                        "default": "standard",
                        "desc": "detailed=+10cr, extreme(8K)=+20cr; fast = quickest, same size and "
                                "price as standard (texture v3.5 only, picked for you if unset)"},
    "texture_version": {"type": "enum", "enum": [""] + TEXTURE_VERSIONS, "default": "",
                        "desc": "Texture model, independent of the geometry model. Empty = Tripo "
                                "derives it (v3.0, or v2.5 for v2.5 geometry). v3.5-20260815 = "
                                "newest; adds texture_quality=fast and delight"},
    "delight": {"type": "bool", "default": True,
                "desc": "Strip baked-in lighting from the reference before texturing "
                        "(texture v3.5 only; off = keep the original shading)"},
    "geometry_quality": {"type": "enum", "enum": ["standard", "detailed"],
                         "default": "standard", "desc": "detailed(Ultra)=+20cr, v3.0+ only"},
    "face_limit": {"type": "int", "min": 48, "max": 2_000_000, "default": None,
                   "desc": "Target faces; adaptive if empty. P1: 50-20000; "
                           "P2: 48-50000 tri / 48-25000 quad"},
    "quad": {"type": "bool", "default": False,
             "desc": "Quad topology (H v3.0+: +5cr, FBX output; P2: native quads)"},
    "smart_low_poly": {"type": "bool", "default": False, "desc": "+10cr, v3.0+"},
    "generate_parts": {"type": "bool", "default": False,
                       "desc": "+20cr, v3.0+; incompatible with texture/pbr/quad"},
    "auto_size": {"type": "bool", "default": False, "desc": "Real-world meters, v3.0+"},
    "orientation": {"type": "enum", "enum": ["default", "align_image"], "default": "default",
                    "desc": "align_image needs texture=true"},
    "texture_alignment": {"type": "enum", "enum": ["original_image", "geometry"],
                          "default": "original_image"},
    "model_seed": {"type": "int", "default": None, "desc": "Geometry seed"},
    "texture_seed": {"type": "int", "default": None, "desc": "Texture seed"},
    "compress": {"type": "enum", "enum": ["", "geometry"], "default": "",
                 "desc": "meshopt compression, v3.0+"},
    "export_uv": {"type": "bool", "default": True},
}

# --- Per-model form overrides (consumed by the UI via /api/ops) -------------
# For each mesh_gen field, "per_model" maps a model id to {hidden?, min?, max?,
# desc?, default?} so the form can show only what the chosen model actually
# takes, with that model's real ranges. Hidden-ness is DERIVED from the same
# allowlists clean_mesh_options enforces — one source of truth, the form can
# never drift from the cleaner.
_P_FAMILY_ALLOWED = {"P1-20260311": P1_ALLOWED, "P2-20260801": P2_ALLOWED}


def _build_mesh_per_model() -> None:
    for key, fspec in MESH_GEN_FIELDS.items():
        if key == "model":
            continue
        pm: dict[str, dict[str, Any]] = {}
        for m, allowed in _P_FAMILY_ALLOWED.items():
            if key not in allowed:
                pm[m] = {"hidden": True}
        if key in V30_PLUS_PARAMS:
            pm["v2.5-20250123"] = {"hidden": True}
        if pm:
            fspec.setdefault("per_model", {}).update(pm)
    # Family-true ranges + descriptions (API-verified 2026-08-25).
    MESH_GEN_FIELDS["face_limit"].setdefault("per_model", {}).update({
        "P1-20260311": {"min": 50, "max": 20_000,
                        "desc": "Target faces; adaptive if empty. P1 range: 50-20000"},
        "P2-20260801": {"min": 48, "max": 50_000,
                        "desc": "Face budget; adaptive if empty. P2: 48-50000 tri, "
                                "48-25000 with quad on (a quad counts as one face)"},
    })
    MESH_GEN_FIELDS["quad"].setdefault("per_model", {}).update({
        "P2-20260801": {"desc": "Native quad topology (P2's marquee feature; "
                                "caps face budget at 25000)"},
    })


_build_mesh_per_model()

_IMAGE_COMMON_FIELDS: dict[str, Any] = {
    "prompt": {"type": "text", "default": "", "desc": "Subject prompt (project prompt if empty)"},
    "model": {"type": "enum", "enum": list(IMAGE_MODELS), "default": DEFAULT_IMAGE_MODEL,
              "desc": _MODEL_NOTES},
    "resolution": {"type": "enum", "enum": ["0.5k", "1k", "2k", "4k"], "default": "4k",
                   "desc": "Mapped per model (grok caps at 2K; MAI/luma ignore; "
                           "0.5k = gemini-flash + gpt-image @openai)"},
    "quality": {"type": "enum", "enum": ["low", "medium", "high"], "default": "high",
                "desc": "gpt-image family only (2.5 flare/sunburst, 2); other models ignore it"},
    "aspect_ratio": {"type": "enum", "enum": ["1:1", "3:2", "2:3", "16:9", "9:16"], "default": "1:1"},
    "seed": {"type": "int", "default": None, "desc": "Honored by FLUX 2 only"},
    "character": {"type": "bool", "default": False,
                  "desc": "Append the character suffix (T-pose etc.) to the prompt"},
    "character_suffix": {"type": "text", "default": CHARACTER_SUFFIX,
                         "desc": "Editable suffix used when 'character' is checked"},
    "n": {"type": "int", "min": 1, "max": 8, "default": 1, "desc": "Parallel candidates"},
}

OP_SPECS: dict[str, dict[str, Any]] = {
    "ref_set": {
        "provider": "local",
        "fields": {},
        "desc": "Container of reference images. Upload/remove refs on the node; "
                "duplicate it to branch a different set. image_gen children use its refs.",
    },
    "image_gen": {
        "provider": "wavespeed",
        "fields": {
            **_IMAGE_COMMON_FIELDS,
            "grid_contract": {"type": "bool", "default": True,
                              "desc": "Append the 4-pane turnaround contract to the prompt"},
            "contract": {"type": "text", "default": GRID_CONTRACT,
                         "desc": "The boilerplate appended to your prompt (edit freely)"},
        },
    },
    "image_edit": {
        "provider": "wavespeed",
        "fields": {
            **_IMAGE_COMMON_FIELDS,
            "grid_contract": {"type": "bool", "default": False,
                              "desc": "Append the 4-pane contract (needed only if the edit should "
                                      "re-establish the grid layout; editing a grid usually keeps it)"},
            "contract": {"type": "text", "default": GRID_CONTRACT},
        },
    },
    "split": {
        "provider": "local",
        "fields": {
            "auto_label": {"type": "bool", "default": True,
                           "desc": "Vision pass (Haiku 4.5) reads which view is in each pane and "
                                   "permutes the crop — fixes gpt-image-2 swapping left/right. "
                                   "Ignored if a mapping is set; falls back to default if uncertain"},
            "mapping": {"type": "json", "default": None,
                        "desc": "Override pane mapping {view: [col,row]}; wins over auto_label"},
            "trim": {"type": "float", "min": 0.0, "max": 0.1, "default": 0.01,
                     "desc": "Edge trim fraction per pane"},
        },
    },
    "mesh_gen": {
        "provider": "tripo",
        "endpoint": "generation/multiview-to-model",
        "fields": {**MESH_GEN_FIELDS,
                   "views": {"type": "json", "default": None,
                             "desc": "Subset of views to send, e.g. [\"front\",\"back\"]; default all 4"},
                   "ref_index": {"type": "int", "min": 0, "default": 0,
                                 "desc": "Off a ref_set: which reference image to mesh from (single-image → 3D). "
                                         "Tripo takes one image here; the model imagines the unseen sides"},
                   "n": {"type": "int", "min": 1, "max": 6, "default": 1, "desc": "Parallel candidates"}},
        "credits": "20 (H) / 30 (P1) / P2 preview unpublished + quality surcharges",
        "desc": "Multiview mesh from a split node — or single-image mesh when "
                "branched directly off an image node (no split needed).",
    },
    "image_to_multiview": {
        "provider": "tripo",
        "endpoint": "generation/image-to-multiview",
        "fields": {"model_seed": {"type": "int", "default": None}},
        "credits": "10",
    },
    "texture": {
        "provider": "tripo",
        "endpoint": "models/texture",
        "fields": {
            "model": {"type": "enum", "enum": TEXTURE_VERSIONS, "default": "v3.0-20250812",
                      "desc": "v3.5-20260815 = newest texture model (adds fast + delight); "
                              "v3.0 suits v3.x geometry, v2.5 suits v2.5 geometry"},
            "texture": {"type": "bool", "default": True},
            "pbr": {"type": "bool", "default": True},
            "texture_quality": {"type": "enum", "enum": TEXTURE_QUALITIES, "default": "standard",
                                "desc": "fast = quickest, same size and price as standard (v3.5 only)",
                                "per_model": {m: {"enum": TEXTURE_QUALITIES[1:]}
                                              for m in TEXTURE_VERSIONS if m != TEXTURE_V35}},
            "delight": {"type": "bool", "default": True,
                        "desc": "Strip baked-in lighting from the reference before texturing",
                        "per_model": {m: {"hidden": True}
                                      for m in TEXTURE_VERSIONS if m != TEXTURE_V35}},
            "texture_alignment": {"type": "enum", "enum": ["original_image", "geometry"], "default": "original_image"},
            "texture_seed": {"type": "int", "default": None},
        },
        "credits": "10 / 20 (detailed) / 30 (extreme); fast = standard",
    },
    "retopo": {
        "provider": "tripo",
        "endpoint": "mesh/decimate",
        "fields": {
            "model": {"type": "enum", "enum": [RETOPO_V3, "v2.0", "v1.0"], "default": RETOPO_V3,
                      "desc": "v3.0 = newest retopology: better edge flow, steadier, faster, "
                              "optional UV unwrap (35cr tri / 40cr quad); v2.0 = previous smart "
                              "retopology (30cr); v1.0 = basic decimation (10cr)"},
            "face_limit": {"type": "int", "min": 50, "max": 500_000, "default": 10000,
                           "per_model": {RETOPO_V3: {
                               "min": RETOPO_V3_FACES[0], "max": RETOPO_V3_FACES[1],
                               "desc": "Target faces: 500-20000 triangles, 500-10000 with quad on. "
                                       "Empty = adaptive"}}},
            "quad": {"type": "bool", "default": False,
                     "desc": "Quad mesh output (v3.0: 40cr instead of 35)"},
            "smart_uv": {"type": "bool", "default": True,
                         "desc": "Unwrap UVs with Smart UV in the same task — free on v3.0 "
                                 "(fewer seams, better packing). No atlas preview; use the uv "
                                 "op if you want that",
                         "per_model": {"v2.0": {"hidden": True}, "v1.0": {"hidden": True}}},
            "bake": {"type": "bool", "default": True, "desc": "Bake original texture onto result",
                     "per_model": {"v1.0": {"hidden": True}}},
            "part_names": {"type": "json", "default": None,
                           "desc": "Only decimate these segmented parts, e.g. [\"tripo_part_0\"]",
                           "per_model": {"v1.0": {"hidden": True}}},
        },
        "credits": "35 tri / 40 quad (v3.0) / 30 (v2.0) / 10 (v1.0)",
    },
    "uv": {
        "provider": "tripo",
        "endpoint": "mesh/uv",
        "fields": {
            "bake": {"type": "bool", "default": True,
                     "desc": "Carry the existing textures onto the new UV layout "
                             "(off = geometry + UVs only)"},
            "export_orientation": {"type": "enum", "enum": ["", "+x", "-x", "+y", "-y"],
                                   "default": "", "desc": "Exported facing (empty = unchanged)"},
            "compress": {"type": "enum", "enum": ["", "geometry"], "default": "",
                         "desc": "meshopt geometry compression"},
        },
        "credits": "20",
        "desc": "Smart UV: AI re-unwrap (fewer seams, better packing) that remaps the "
                "model's existing textures, rig and animation onto the new layout. Works "
                "on any model, imports included. Input must be <= 80,000 triangles (a "
                "quad counts as two) — retopo first if it is bigger. The result also "
                "carries a UV atlas preview image.",
    },
    "segment": {
        "provider": "tripo",
        "endpoint": "mesh/segment",
        "fields": {
            "model": {"type": "enum", "enum": ["v2.0-20260430", "v1.0-20250506"], "default": "v2.0-20260430"},
            "segmentation_granularity": {"type": "enum", "enum": ["simple", "balanced", "detailed"], "default": "balanced"},
            "split_by_connectivity": {"type": "bool", "default": False},
        },
        "credits": "40+",
    },
    "complete": {
        "provider": "tripo",
        "endpoint": "mesh/complete",
        "fields": {
            "completion_mode": {"type": "enum", "enum": ["ai_completion", "quick_cap"], "default": "ai_completion"},
            "part_names": {"type": "json", "default": None},
        },
        "credits": "50 (ai) / 30 (quick_cap)",
    },
    "rig": {
        "provider": "tripo",
        "endpoint": "animations/rig",
        "fields": {
            "model": {"type": "enum", "enum": ["auto"] + RIG_MODELS, "default": "auto",
                      "desc": "auto = v3.0, Tripo's newest rigger: full-body humanoid rig WITH "
                              "finger bones + engine skeleton presets, and it plays BOTH preset "
                              "libraries (incl. the 90+ preset:biped:* dances/emotes); "
                              "non-humanoids at v2.5 quality. v1.0 = legacy biped rig "
                              "(no fingers); v2.5 = previous creature rigger"},
            "rig_type": {"type": "enum", "enum": ["auto"] + RIG_TYPES,
                         "default": "auto",
                         "desc": "auto = use the free rig-check result; others = a skeleton "
                                 "matching none of the named types (v3.0 only)",
                         "per_model": {RIG_V1: {"enum": ["auto", "biped"]},
                                       RIG_V25: {"enum": ["auto"] + RIG_TYPES[:-1]}}},
            "spec": {"type": "enum", "enum": RIG_SPECS, "default": "tripo",
                     "desc": "Skeleton naming, bipeds only. unreal = UE5 Mannequin, unity = "
                             "Unity Humanoid, vrm = VRM 1.0, actorcore = ActorCore (these four "
                             "need v3.0). Eidoverse avatars convert from tripo naming",
                     "per_model": {RIG_V1: {"enum": ["tripo", "mixamo"]},
                                   RIG_V25: {"enum": ["tripo", "mixamo"]}}},
            "out_format": {"type": "enum", "enum": ["glb", "fbx"], "default": "glb"},
        },
        "credits": "25 (+0 rig-check)",
    },
    "retarget": {
        "provider": "tripo",
        "endpoint": "animations/retarget",
        "fields": {
            "animations": {"type": "json", "default": None,
                           "desc": "Up to 5 preset names; the valid set depends on the parent "
                                   "RIG's version (listed under presets). Rig v3.0 takes both "
                                   "libraries: preset:idle, preset:walk, preset:jump… and "
                                   "preset:biped:dance_01, preset:biped:wave_goodbye_01… ; "
                                   "v1.0: preset:biped:* only; v2.5: the short list only. "
                                   "Other spellings are translated when the clip exists. "
                                   "Empty = idle"},
            "out_format": {"type": "enum", "enum": ["glb", "fbx"], "default": "glb"},
            "export_with_geometry": {"type": "bool", "default": True},
            "animate_in_place": {"type": "bool", "default": True,
                                 "desc": "Cancel root motion (Tripo's own default is false; walking "
                                         "presets translate through space and look broken in a viewer)"},
        },
        "presets": RETARGET_PRESETS,
        "credits": "10 per animation",
    },
    "convert": {
        "provider": "tripo",
        "endpoint": "models/convert",
        "fields": {
            "format": {"type": "enum", "enum": ["GLTF", "FBX", "USDZ", "OBJ", "STL", "3MF"], "default": "FBX"},
            "quad": {"type": "bool", "default": False},
            "face_limit": {"type": "int", "default": None},
            "texture_size": {"type": "int", "default": 4096},
            "texture_format": {"type": "enum",
                               "enum": ["JPEG", "PNG", "WEBP", "BMP", "DPX", "HDR", "OPEN_EXR", "TARGA", "TIFF"],
                               "default": "PNG"},
            "bake": {"type": "bool", "default": True},
            "pack_uv": {"type": "bool", "default": False},
            "force_symmetry": {"type": "bool", "default": False},
            "flatten_bottom": {"type": "bool", "default": False},
            "pivot_to_center_bottom": {"type": "bool", "default": False},
            "scale_factor": {"type": "float", "default": 1.0},
            "with_animation": {"type": "bool", "default": True},
            "export_orientation": {"type": "enum", "enum": ["+x", "-x", "+y", "-y"], "default": "+x"},
            "fbx_preset": {"type": "enum", "enum": ["blender", "3dsmax", "mixamo"], "default": "blender"},
        },
        "credits": "5-10",
    },
    "rescale": {
        "provider": "local",
        "fields": {
            "target_size": {"type": "float", "default": None,
                            "desc": "Desired largest bounding-box dimension (e.g. metres). "
                                    "Tripo normalizes meshes to largest-dim 1.0, so set this to give "
                                    "the object a real size"},
            "scale_factor": {"type": "float", "default": None,
                             "desc": "Multiply size directly (used only if target_size is empty)"},
        },
        "desc": "Local uniform rescale — free, instant, no API call. Corrects absolute size.",
    },
    "fuse": {
        "provider": "local",
        "fields": {
            "parts": {"type": "json", "default": None,
                      "desc": "Part names to merge into ONE part, e.g. "
                              "[\"tripo_part_0\",\"tripo_part_1\"]. This is the common case — "
                              "start here. Names come from the model's meta.parts / viewer legend."},
            "groups": {"type": "json", "default": None,
                       "desc": "Several independent merges at once: a list of part-name lists, "
                               "e.g. [[\"a\",\"b\"],[\"c\",\"d\"]] — each inner list collapses "
                               "into one part. A flat list here is treated as a single group. "
                               "Parts not listed are left untouched."},
        },
        "desc": "Local part merge — free, instant, no API call. Baked-in-place, so geometry, "
                "per-part materials and absolute size are preserved; the buffer does not grow. "
                "Cuts an over-segmented mesh (60+ parts) down to a handful. In the viewer, "
                "lasso-select parts or tick the legend to build a group, then fuse.",
    },
    "drop": {
        "provider": "local",
        "fields": {
            "parts": {"type": "json", "default": None,
                      "desc": "Part names to DELETE from the mesh, e.g. [\"tripo_part_5\"]. "
                              "Names come from the model's meta.parts / viewer legend."},
        },
        "desc": "Local part delete — free, instant, no API call. Removes floating scraps and "
                "unwanted pieces a segmentation revealed; everything else passes through "
                "untouched. In the viewer, lasso/tick parts then hit delete.",
    },
    "import_model": {
        "provider": "local",
        "fields": {},
    },
}

# Options handled by our engine, never sent to Tripo payloads. NB: "model" is a
# real Tripo field (retopo/rig/texture) and must NOT be listed here; WaveSpeed
# image ops never go through clean_generic_options, so their fields are safe.
CONTROL_KEYS = {"n", "views", "use_refs", "grid_contract", "contract", "prompt",
                "character", "character_suffix", "resolution", "quality",
                "aspect_ratio", "mapping", "trim", "rig_type"}


def clean_mesh_options(opts: dict[str, Any]) -> dict[str, Any]:
    """Validate + strip mesh_gen options for the chosen model version.
    Returns provider payload fragment (without inputs)."""
    model = opts.get("model") or "v3.1-20260211"
    if model not in MESH_MODELS:
        raise ValueError(f"unknown mesh model {model!r}; valid: {MESH_MODELS}")
    out: dict[str, Any] = {"model": model}
    for key, spec in MESH_GEN_FIELDS.items():
        if key in ("model",):
            continue
        val = opts.get(key, spec.get("default"))
        if val is None or val == "":
            continue
        if model.startswith("P"):
            allowed = P2_ALLOWED if model.startswith("P2") else P1_ALLOWED
            if key not in allowed:
                continue
        elif key in V30_PLUS_PARAMS and _H_ORDER.get(model, 99) < _H_ORDER["v3.0-20250812"]:
            continue  # strip v3.0+-only params for v2.5
        out[key] = val
    if out.get("generate_parts"):
        for bad in ("texture", "pbr", "quad"):
            out.pop(bad, None)
        out["texture"] = False
    if out.get("pbr"):
        out["texture"] = True
    if out.get("orientation") == "align_image" and not out.get("texture", True):
        out["orientation"] = "default"
    _clean_texture_version(out)
    return out


def _clean_texture_version(out: dict[str, Any]) -> None:
    """texture_version / delight / texture_quality=fast on generation payloads.
    `fast` exists only on texture v3.5: an unset version is pinned to v3.5 for
    it, an explicit other version is refused (Tripo would 1004 anyway)."""
    if out.get("texture") is False:
        for k in ("texture_version", "delight"):
            out.pop(k, None)
        if out.get("texture_quality") == "fast":
            out.pop("texture_quality")
        return
    tv = out.get("texture_version")
    if tv and tv not in TEXTURE_VERSIONS:
        raise ValueError(f"unknown texture_version {tv!r}; valid: {TEXTURE_VERSIONS}")
    if out.get("texture_quality") == "fast":
        if tv and tv != TEXTURE_V35:
            raise ValueError(f"texture_quality=fast needs texture_version {TEXTURE_V35} "
                             f"(got {tv}); pick standard or switch the texture version")
        out["texture_version"] = tv = TEXTURE_V35
    if tv != TEXTURE_V35:
        out.pop("delight", None)   # only v3.5 reads it — keep payloads honest


def clean_generic_options(op_type: str, opts: dict[str, Any]) -> dict[str, Any]:
    """Build provider payload fragment for non-mesh_gen tripo ops from the spec.
    Fields the spec marks hidden for the chosen `model` (per_model) are never
    sent — the same table drives the UI form, so the two cannot drift."""
    spec = OP_SPECS[op_type]
    fields = spec["fields"]
    model = opts.get("model", (fields.get("model") or {}).get("default"))
    out: dict[str, Any] = {}
    for key, fspec in fields.items():
        if key in CONTROL_KEYS:
            continue
        eff = {**fspec, **(fspec.get("per_model", {}).get(model) or {})}
        if eff.get("hidden"):
            continue
        val = opts.get(key, eff.get("default"))
        if val is None or val == "":
            continue
        if eff["type"] == "enum" and val not in eff["enum"]:
            raise ValueError(f"{op_type}.{key}: {val!r} not valid"
                             f"{' for ' + model if model and eff['enum'] != fspec['enum'] else ''}"
                             f"; choose from {eff['enum']}")
        out[key] = val
    check = _OP_CHECKS.get(op_type)
    if check:
        check(out)
    return out


def _check_retopo(out: dict[str, Any]) -> None:
    if out.get("model") != RETOPO_V3:
        return
    fl = out.get("face_limit")
    if fl is None:
        return  # v3.0: omitted = adaptive reduction
    lo, hi = RETOPO_V3_FACES
    if out.get("quad"):
        hi = RETOPO_V3_QUAD_MAX
    if not lo <= int(fl) <= hi:
        raise ValueError(f"retopo v3.0 face_limit must be {lo}-{hi}"
                         f"{' with quad on' if out.get('quad') else ''} (got {fl}); "
                         "leave it empty for adaptive, or use v2.0 for bigger budgets")


_OP_CHECKS = {"retopo": _check_retopo}


# --- rig / retarget resolution ------------------------------------------------

def resolve_rig_model(model: str | None, rig_type: str, spec: str | None) -> str:
    """Pick + validate the rig model version for a (resolved) rig_type/spec."""
    if model in (None, "", "auto"):
        model = RIG_V3            # v3.0 covers every rig type (non-bipeds at v2.5 quality)
    if model not in RIG_MODELS:
        raise ValueError(f"unknown rig model {model!r}; valid: auto, {RIG_MODELS}")
    if model == RIG_V1 and rig_type != "biped":
        raise ValueError(f"rig v1.0 is biped-only (this model is {rig_type}); use v3.0 or auto")
    if rig_type == "others" and model != RIG_V3:
        raise ValueError("rig_type 'others' needs rig model v3.0-20260909 (or auto)")
    if spec in RIG_V3_ONLY_SPECS and model != RIG_V3:
        raise ValueError(f"spec {spec!r} (engine skeleton preset) needs rig model "
                         f"{RIG_V3} (or auto); {model} only knows tripo/mixamo")
    return model


def rig_version_of(rig_opts: dict[str, Any]) -> str | None:
    """Which rig model a rig node actually ran. New nodes record it; older ones
    are inferred from the auto rule they ran under (biped -> v1.0, else v2.5)."""
    if rig_opts.get("model_resolved"):
        return rig_opts["model_resolved"]
    m = rig_opts.get("model")
    if m in RIG_MODELS:
        return m
    rt = rig_opts.get("rig_type_resolved") or rig_opts.get("rig_type")
    if rt in (None, "", "auto"):
        return None
    return RIG_V1 if rt == "biped" else RIG_V25


def resolve_retarget_animations(animations: Any, rig_version: str | None) -> list[str]:
    """Validate + translate retarget presets against the parent rig's library.
    v1.0 says preset:biped:walk where v2.5 says preset:walk — translate when the
    rig's library has the same clip under the other spelling, otherwise refuse
    with the valid list (Tripo's own 1004 'invalid animation' names no
    alternatives, and some bad names only fail after a billed-looking wait).
    v3.0 rigs take both spellings as-is."""
    if animations in (None, "", []):
        animations = ["preset:biped:idle" if rig_version == RIG_V1 else "preset:idle"]
    if isinstance(animations, str):
        animations = [animations]
    names = [str(a).strip() for a in animations if str(a).strip()]
    if len(names) > RETARGET_MAX_ANIMATIONS:
        raise ValueError(f"retarget takes at most {RETARGET_MAX_ANIMATIONS} animations per "
                         f"node (got {len(names)}); branch another retarget for the rest")
    valid = RETARGET_PRESETS.get(rig_version or "")
    if not valid:
        return names              # unknown rig lineage: let Tripo judge
    out: list[str] = []
    for name in names:
        if name in valid:
            out.append(name)
            continue
        clip = name.removeprefix("preset:").removeprefix("biped:")
        alt = (f"preset:biped:{clip}" if rig_version == RIG_V1 else f"preset:{clip}")
        if alt in valid:
            out.append(alt)
            continue
        hint = ("" if rig_version != RIG_V25 else
                " — the 90+ preset:biped:* library (dances, emotes, sports) needs a "
                f"rig made with model {RIG_V3} (or {RIG_V1})")
        raise ValueError(f"{name!r} is not a preset for rig {rig_version}; valid: "
                         f"{', '.join(valid)}{hint}")
    return list(dict.fromkeys(out))
