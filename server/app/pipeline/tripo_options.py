"""Catalog of Tripo v3 options per op — single source of truth for
API payload validation AND the UI's option forms (served at /api/ops).

Each field: {type, enum?, default?, min?, max?, desc, requires_model_gte?}
Model ordering for gates: v2.5-20250123 < v3.0-20250812 < v3.1-20260211.
P1-20260311 is a separate low-poly family with its own allowlist.
"""
from __future__ import annotations

from typing import Any

from .image_models import DEFAULT_IMAGE_MODEL, IMAGE_MODELS
from .prompts import CHARACTER_SUFFIX, GRID_CONTRACT

_MODEL_NOTES = "; ".join(f"{k}: {v['notes']}" for k, v in IMAGE_MODELS.items())

MESH_MODELS = ["v3.1-20260211", "v3.0-20250812", "v2.5-20250123", "P1-20260311"]
_H_ORDER = {"v2.5-20250123": 0, "v3.0-20250812": 1, "v3.1-20260211": 2}

# Params only valid on H-series >= v3.0
V30_PLUS_PARAMS = {"texture_quality", "geometry_quality", "auto_size", "quad",
                   "smart_low_poly", "generate_parts", "compress"}
# Params supported by the P1 low-poly family
P1_ALLOWED = {"texture", "pbr", "texture_quality", "auto_size", "compress",
              "face_limit", "model_seed", "texture_seed", "orientation",
              "texture_alignment", "export_uv"}

MESH_GEN_FIELDS: dict[str, dict[str, Any]] = {
    "model": {"type": "enum", "enum": MESH_MODELS, "default": "v3.1-20260211",
              "desc": "Tripo model version (P1 = clean low-poly family)"},
    "texture": {"type": "bool", "default": True, "desc": "Generate texture"},
    "pbr": {"type": "bool", "default": True, "desc": "PBR maps (forces texture)"},
    "texture_quality": {"type": "enum", "enum": ["standard", "detailed", "extreme"],
                        "default": "standard", "desc": "detailed=+10cr, extreme(8K)=+20cr"},
    "geometry_quality": {"type": "enum", "enum": ["standard", "detailed"],
                         "default": "standard", "desc": "detailed(Ultra)=+20cr, v3.0+ only"},
    "face_limit": {"type": "int", "min": 50, "max": 2_000_000, "default": None,
                   "desc": "Target faces; adaptive if empty. P1: 50-20000"},
    "quad": {"type": "bool", "default": False, "desc": "Quad topology (+5cr, FBX output, v3.0+)"},
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

_IMAGE_COMMON_FIELDS: dict[str, Any] = {
    "prompt": {"type": "text", "default": "", "desc": "Subject prompt (project prompt if empty)"},
    "model": {"type": "enum", "enum": list(IMAGE_MODELS), "default": DEFAULT_IMAGE_MODEL,
              "desc": _MODEL_NOTES},
    "resolution": {"type": "enum", "enum": ["0.5k", "1k", "2k", "4k"], "default": "4k",
                   "desc": "Mapped per model (grok caps at 2K; MAI/luma ignore; 0.5k = gemini-flash only)"},
    "quality": {"type": "enum", "enum": ["low", "medium", "high"], "default": "high",
                "desc": "gpt-image-2 only; other models ignore it"},
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
        "credits": "20 (H) / 30 (P1) + quality surcharges",
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
            "model": {"type": "enum", "enum": ["v3.0-20250812", "v2.5-20250123"], "default": "v3.0-20250812"},
            "texture": {"type": "bool", "default": True},
            "pbr": {"type": "bool", "default": True},
            "texture_quality": {"type": "enum", "enum": ["standard", "detailed", "extreme"], "default": "standard"},
            "texture_alignment": {"type": "enum", "enum": ["original_image", "geometry"], "default": "original_image"},
            "texture_seed": {"type": "int", "default": None},
        },
        "credits": "10 / 20 (detailed) / 30 (extreme)",
    },
    "retopo": {
        "provider": "tripo",
        "endpoint": "mesh/decimate",
        "fields": {
            "model": {"type": "enum", "enum": ["v2.0", "v1.0"], "default": "v2.0",
                      "desc": "v2.0 = smart retopology (30cr), v1.0 = basic decimation (10cr)"},
            "face_limit": {"type": "int", "min": 50, "max": 500_000, "default": 10000},
            "quad": {"type": "bool", "default": False},
            "bake": {"type": "bool", "default": True, "desc": "Bake original texture onto result"},
        },
        "credits": "30 (v2.0) / 10 (v1.0)",
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
            "model": {"type": "enum", "enum": ["auto", "v1.0-20240301", "v2.5-20260210"], "default": "auto",
                      "desc": "auto = v1.0 for bipeds (cleaner retargets, 90+ presets), v2.5 for "
                              "non-humanoid rig types (quadruped etc.)"},
            "rig_type": {"type": "enum",
                         "enum": ["auto", "biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic"],
                         "default": "auto", "desc": "auto = use free rig-check result"},
            "spec": {"type": "enum", "enum": ["tripo", "mixamo"], "default": "tripo", "desc": "Bone naming"},
            "out_format": {"type": "enum", "enum": ["glb", "fbx"], "default": "glb"},
        },
        "credits": "25 (+0 rig-check)",
    },
    "retarget": {
        "provider": "tripo",
        "endpoint": "animations/retarget",
        "fields": {
            "animations": {"type": "json", "default": ["preset:biped:idle"],
                           "desc": "Preset names depend on the RIG version: rig v1.0 -> preset:biped:idle, "
                                   "preset:biped:walk, preset:biped:run, dance_01... ; rig v2.5 -> preset:idle, "
                                   "preset:walk, preset:quadruped:walk etc."},
            "out_format": {"type": "enum", "enum": ["glb", "fbx"], "default": "glb"},
            "bake_animation": {"type": "bool", "default": True, "desc": "glb only"},
            "export_with_geometry": {"type": "bool", "default": True},
            "animate_in_place": {"type": "bool", "default": True,
                                 "desc": "Cancel root motion (Tripo's own default is false; walking "
                                         "presets translate through space and look broken in a viewer)"},
        },
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
            "groups": {"type": "json", "default": None,
                       "desc": "List of part-name lists; each inner list of 2+ names "
                               "(e.g. [\"tripo_part_3\",\"tripo_part_7\"]) collapses into one "
                               "part. Parts not listed are left untouched."},
            "parts": {"type": "json", "default": None,
                      "desc": "Shorthand for a single group — merge just these names into one part."},
        },
        "desc": "Local part merge — free, instant, no API call. Baked-in-place, so geometry, "
                "per-part materials and absolute size are preserved; the buffer does not grow. "
                "Cuts an over-segmented mesh (60+ parts) down to a handful. In the viewer, "
                "lasso-select parts or tick the legend to build a group, then fuse.",
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
        if model.startswith("P1"):
            if key not in P1_ALLOWED:
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
    return out


def clean_generic_options(op_type: str, opts: dict[str, Any]) -> dict[str, Any]:
    """Build provider payload fragment for non-mesh_gen tripo ops from the spec."""
    spec = OP_SPECS[op_type]
    out: dict[str, Any] = {}
    for key, fspec in spec["fields"].items():
        if key in CONTROL_KEYS:
            continue
        val = opts.get(key, fspec.get("default"))
        if val is None or val == "":
            continue
        if fspec["type"] == "enum" and val not in fspec["enum"]:
            raise ValueError(f"{op_type}.{key}: {val!r} not in {fspec['enum']}")
        out[key] = val
    return out
