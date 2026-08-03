"""Op implementations. Each takes (engine, node) and must:
- persist provider task ids as soon as they exist (restart safety),
- archive every provider output to the node's folder immediately,
- record cost/credits on the node.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..clients import get_tripo, get_wavespeed
from ..clients.tripo import TripoError
from ..models import AssetKind, Node, NodeStatus, OpType
from ..services.splitter import split_grid
from .prompts import VIEW_ORDER, assemble_prompt
from .tripo_options import clean_generic_options, clean_mesh_options, OP_SPECS

log = logging.getLogger(__name__)


# ---------- shared helpers ----------

async def _first_asset(eng, node_id: str, kind: AssetKind) -> Path | None:
    assets = await eng.node_assets(node_id, kind)
    return eng.abs(assets[0].path) if assets else None


async def _model_input(eng, parent: Node) -> tuple[str, bool]:
    """Resolve the Tripo `input` for a post-op from the parent node.
    Returns (input_value, used_task_id). Prefers chaining the provider task id;
    falls back to uploading our archived model file.
    NB: post-processing `input` is a BARE STRING (task_id | file_token | URL).
    The object form {"file_token": ...} belongs to the v2-style generation
    endpoints only; animations/* reject it with 1004 "input is required"
    (verified live 2026-08-03 — this is what broke rigging re-imported models)."""
    if parent.provider == "tripo" and parent.provider_task_id:
        return parent.provider_task_id, True
    model_path = await _first_asset(eng, parent.id, AssetKind.model)
    if not model_path:
        raise RuntimeError(f"parent node {parent.id} has no model output to operate on")
    token = await get_tripo().upload_file(model_path)
    return token, False


async def _run_tripo(eng, node: Node, endpoint: str, payload: dict):
    """Create/resume + poll a tripo task, persisting id + progress on the node."""
    tripo = get_tripo()

    async def on_submit(task_id: str):
        await eng.update_node(node.id, provider="tripo", provider_task_id=task_id)

    async def on_progress(p: int):
        await eng.update_node(node.id, progress=p)

    return await tripo.run_task(
        endpoint, payload,
        on_submit=on_submit, on_progress=on_progress,
        existing_task_id=node.provider_task_id if node.provider == "tripo" else None,
    )


async def _run_tripo_postop(eng, node: Node, endpoint: str, payload_base: dict):
    """Post-op with input resolution + expired-task fallback to archived GLB."""
    parent = await eng.get_node(node.parent_id)
    input_val, used_task_id = await _model_input(eng, parent)
    try:
        return await _run_tripo(eng, node, endpoint, {**payload_base, "input": input_val})
    except TripoError as e:
        expired = "expired" in str(e).lower() or getattr(e, "code", None) in (2006, 2015)
        if not (used_task_id and expired):
            raise
        log.warning("task_id chain expired for node %s; falling back to archived model", node.id)
        await eng.update_node(node.id, provider_task_id=None)
        model_path = await _first_asset(eng, parent.id, AssetKind.model)
        if not model_path:
            raise
        token = await get_tripo().upload_file(model_path)
        return await _run_tripo(eng, node, endpoint, {**payload_base, "input": token})


async def _archive_model_outputs(eng, node: Node, result, model_ext: str = "glb"):
    d = eng.node_dir(node.project_id, node.id)
    out = result.output
    if out.get("model_url"):
        # respect actual extension from URL when recognizable
        url = out["model_url"].split("?")[0]
        ext = url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else model_ext
        if ext not in {"glb", "gltf", "fbx", "obj", "usdz", "stl", "3mf", "zip"}:
            ext = model_ext
        path = await get_tripo().download(out["model_url"], d / f"model.{ext}")
        meta = {"format": ext}
        if ext in ("glb", "gltf"):
            from .meshinfo import glb_bounds
            b = glb_bounds(path)
            if b:
                meta["bounds"] = b
        await eng.add_asset(node, AssetKind.model, path, meta)
    if out.get("rendered_image_url"):
        path = await get_tripo().download(out["rendered_image_url"], d / "render.png")
        await eng.add_asset(node, AssetKind.render, path, {})
    if result.credits:
        await eng.update_node(node.id, credits=result.credits)


# ---------- ops ----------

async def op_ref_set(eng, node: Node) -> None:
    """Container of reference images — completes immediately; refs are uploaded
    onto the node via the API. Empty sets are allowed (fill later)."""
    return


async def _first_image_asset(eng, node_id: str) -> Path | None:
    for kind in (AssetKind.grid, AssetKind.render, AssetKind.view):
        p = await _first_asset(eng, node_id, kind)
        if p:
            return p
    return None


async def _run_image_op(eng, node: Node, ref_paths: list[Path], is_grid_default: bool,
                        edit_mode: bool = False, output_grid: bool | None = None) -> None:
    """Shared body of image_gen / image_edit — dispatches to the provider named
    by the model registry entry (wavespeed | openrouter | bfl).

    output_grid decouples "is the OUTPUT a 4-view grid" from "append the grid
    contract to the prompt" — an edit of a grid stays a grid even when no
    contract text is added to the edit prompt."""
    from ..config import get_settings
    from .image_models import DEFAULT_IMAGE_MODEL, model_entry

    project = await eng.get_project(node.project_id)
    opts = node.options
    subject = (opts.get("prompt") or project.prompt or "").strip()
    if not subject:
        raise RuntimeError("no prompt: set node options.prompt or project prompt")
    contract_on = opts.get("grid_contract", is_grid_default)
    prompt = assemble_prompt(subject, {**opts, "grid_contract": contract_on})
    is_grid = output_grid if output_grid is not None else contract_on

    model_key = opts.get("model") or DEFAULT_IMAGE_MODEL
    entry = model_entry(model_key)
    max_refs = entry.get("max_refs", 0) if entry.get("supports_refs") else 0
    if ref_paths and not max_refs:
        raise RuntimeError(f"model {model_key} does not accept reference/input images")
    refs = ref_paths[:max_refs]

    dest = eng.node_dir(node.project_id, node.id) / ("grid.png" if is_grid else "image.png")
    provider = "wavespeed" if get_settings().mock_apis else entry["provider"]

    if provider == "wavespeed":
        ws = get_wavespeed()
        ref_urls = [await ws.upload_ref(p) for p in refs]
        build = entry.get("ws_request") or (lambda o, r, e: ("openai/gpt-image-2/text-to-image",
                                                             {"prompt": o["_prompt"]}, 0.0))
        endpoint, body, cost = build({**opts, "_prompt": prompt}, ref_urls, edit_mode)

        async def on_submit(pred_id: str):
            await eng.update_node(node.id, provider="wavespeed", provider_task_id=pred_id)

        result = await ws.run(
            endpoint, body, dest, cost_usd=cost, on_submit=on_submit,
            existing_prediction_id=node.provider_task_id if node.provider == "wavespeed" else None,
        )
    elif provider == "openrouter":
        from ..clients.openrouter import OpenRouterImageClient
        await eng.update_node(node.id, provider="openrouter")
        result = await OpenRouterImageClient().generate(
            entry["path"], prompt, dest, ref_paths=refs,
            params=entry["map_options"](opts),
        )
    elif provider == "bfl":
        from ..clients.bfl import BFLClient
        await eng.update_node(node.id, provider="bfl")
        kwargs = {k: v for k, v in entry["map_options"](opts).items() if v is not None}
        result = await BFLClient().generate(
            entry["path"], prompt, dest, ref_paths=refs, **kwargs,
        )
    else:
        raise RuntimeError(f"unknown image provider {provider}")

    await eng.add_asset(node, AssetKind.grid if is_grid else AssetKind.render, dest,
                        {"prompt": prompt, "n_refs": len(refs), "model": model_key})
    await eng.update_node(node.id, cost_usd=result.cost_usd)


async def op_image_gen(eng, node: Node) -> None:
    """t2i at the root; edit-with-references when parented on a ref_set."""
    ref_paths: list[Path] = []
    if node.parent_id:
        parent = await eng.get_node(node.parent_id)
        if parent.op_type == OpType.ref_set:
            refs = await eng.node_assets(parent.id, AssetKind.ref)
            ref_paths = [eng.abs(a.path) for a in refs]
        else:
            raise RuntimeError("image_gen parent must be a ref_set (or none for text-to-image)")
    else:
        # legacy: project-level refs (pre-ref_set projects)
        refs = await eng.project_refs(node.project_id)
        ref_paths = [eng.abs(a.path) for a in refs]
    await _run_image_op(eng, node, ref_paths, is_grid_default=True)


async def op_image_edit(eng, node: Node) -> None:
    """img2img: the parent node's image is the edit input. If the parent image
    was a grid, the output is treated as a grid (layout preserved by the edit)."""
    parent = await eng.get_node(node.parent_id)
    src = await _first_image_asset(eng, parent.id)
    if not src:
        raise RuntimeError("parent node has no image to edit")
    parent_was_grid = bool(await _first_asset(eng, parent.id, AssetKind.grid))
    # output stays a grid if the parent was one OR the contract was requested,
    # regardless of whether contract text is appended to the edit prompt
    output_grid = parent_was_grid or bool(node.options.get("grid_contract"))
    await _run_image_op(eng, node, [src], is_grid_default=False, edit_mode=True,
                        output_grid=output_grid)


async def op_split(eng, node: Node) -> None:
    grid = await _first_asset(eng, node.parent_id, AssetKind.grid)
    if not grid:
        # fall back to any image output (e.g. an edit that was mislabeled
        # 'render' — kind is metadata; the caller asked for a split, trust them)
        grid = await _first_asset(eng, node.parent_id, AssetKind.render)
    if not grid:
        raise RuntimeError("parent node has no image to split (needs a grid or "
                           "image output — generate with grid_contract, or edit a grid)")
    opts = node.options
    trim = float(opts.get("trim", 0.01))

    # mapping priority: explicit override > vision auto-label > default layout
    mapping = opts.get("mapping")
    label_source = "explicit" if mapping else "default"
    if not mapping and opts.get("auto_label", True):
        from ..clients.labeler import label_grid
        detected = await label_grid(grid)
        if detected:
            mapping = detected
            label_source = "auto_label"
    # record what we used so the human can see/override
    await eng.update_node(node.id, options={**opts, "mapping": mapping,
                                            "label_source": label_source})

    views = split_grid(grid, eng.node_dir(node.project_id, node.id),
                       mapping=mapping, trim=trim)
    for view, path in views.items():
        await eng.add_asset(node, AssetKind.view, path, {"view": view})


async def _single_image_mesh(eng, node: Node, src: Path, payload: dict) -> None:
    """Tripo generation/image-to-model from one image (single-image → 3D;
    the model imagines the unseen sides). Tripo takes exactly ONE image here —
    it has no multi-arbitrary-reference mode; multiple images only via
    multiview, which must be orthographic front/left/back/right."""
    token = await get_tripo().upload_file(src)
    # NB: this endpoint wants v2-style `file`, not v3 `input` (verified live)
    payload["file"] = {"type": src.suffix.lstrip(".").lower() or "png",
                       "file_token": token}
    result = await _run_tripo(eng, node, "generation/image-to-model", payload)
    await _archive_model_outputs(eng, node, result,
                                 model_ext="fbx" if payload.get("quad") else "glb")


async def op_mesh_gen(eng, node: Node) -> None:
    """Multiview mesh from a split parent, or single-image mesh
    (Tripo generation/image-to-model) off an image node OR a ref_set."""
    parent = await eng.get_node(node.parent_id)
    opts = node.options
    payload = clean_mesh_options(opts)

    if parent.op_type in (OpType.image_gen, OpType.image_edit):
        src = await _first_image_asset(eng, parent.id)
        if not src:
            raise RuntimeError("parent image node has no image output")
        return await _single_image_mesh(eng, node, src, payload)

    if parent.op_type == OpType.ref_set:
        # mesh straight from a reference photo — no image_gen needed
        refs = await eng.node_assets(parent.id, AssetKind.ref)
        if not refs:
            raise RuntimeError("ref_set is empty — add a reference image first")
        idx = int(opts.get("ref_index", 0))
        if idx < 0 or idx >= len(refs):
            raise RuntimeError(f"ref_index {idx} out of range (ref_set has {len(refs)} images)")
        return await _single_image_mesh(eng, node, eng.abs(refs[idx].path), payload)

    if parent.op_type == OpType.image_to_multiview and parent.provider_task_id:
        payload["inputs"] = [{"task_id": parent.provider_task_id}]
    else:
        wanted = opts.get("views") or VIEW_ORDER
        view_assets = {a.meta.get("view"): a for a in await eng.node_assets(parent.id, AssetKind.view)}
        missing = [v for v in wanted if v not in view_assets]
        if missing:
            raise RuntimeError(f"parent split node lacks views: {missing}")
        if "front" not in wanted:
            raise RuntimeError("Tripo requires the front view")
        if len(wanted) < 2:
            raise RuntimeError("Tripo requires at least 2 views")
        tripo = get_tripo()
        inputs = []
        for view in VIEW_ORDER:
            if view in wanted:
                token = await tripo.upload_file(eng.abs(view_assets[view].path))
                inputs.append({view: {"file_token": token}})
        payload["inputs"] = inputs

    result = await _run_tripo(eng, node, "generation/multiview-to-model", payload)
    await _archive_model_outputs(eng, node, result,
                                 model_ext="fbx" if payload.get("quad") else "glb")


async def op_image_to_multiview(eng, node: Node) -> None:
    parent = await eng.get_node(node.parent_id)
    src = (await _first_asset(eng, parent.id, AssetKind.grid)
           or await _first_asset(eng, parent.id, AssetKind.render)
           or await _first_asset(eng, parent.id, AssetKind.view))
    if not src:
        raise RuntimeError("parent has no image for image_to_multiview")
    token = await get_tripo().upload_file(src)
    payload = clean_generic_options("image_to_multiview", node.options)
    payload["input"] = {"file_token": token}
    result = await _run_tripo(eng, node, "generation/image-to-multiview", payload)
    d = eng.node_dir(node.project_id, node.id)
    for view in VIEW_ORDER:
        url = result.output.get(f"{view}_view_url")
        if url:
            path = await get_tripo().download(url, d / f"{view}.png")
            await eng.add_asset(node, AssetKind.view, path, {"view": view})
    if result.credits:
        await eng.update_node(node.id, credits=result.credits)


def _glb_part_names(path: Path) -> list[str]:
    """Named meshes/nodes inside a GLB — how Tripo segmentation labels parts."""
    import json as _json
    import struct as _struct
    try:
        with open(path, "rb") as f:
            magic, _, _ = _struct.unpack("<4sII", f.read(12))
            if magic != b"glTF":
                return []
            jlen, _ = _struct.unpack("<I4s", f.read(8))
            g = _json.loads(f.read(jlen))
        # prefer NODE names: Tripo names them tripo_part_N (its 'part' vocabulary,
        # and what three.js shows in the viewer); mesh names are the fallback
        names = [n.get("name") for n in g.get("nodes", [])
                 if n.get("name") and n.get("mesh") is not None]
        if len(names) < 2:
            names = [m.get("name") for m in g.get("meshes", []) if m.get("name")]
        return [n for n in names if n]
    except Exception:
        return []


def _generic_postop(op_name: str, endpoint: str, model_ext: str = "glb"):
    async def impl(eng, node: Node) -> None:
        payload = clean_generic_options(op_name, node.options)
        result = await _run_tripo_postop(eng, node, endpoint, payload)
        ext = model_ext
        if op_name == "convert":
            ext = (node.options.get("format") or "FBX").lower().replace("gltf", "glb")
        elif node.options.get("out_format"):
            ext = node.options["out_format"]
        await _archive_model_outputs(eng, node, result, model_ext=ext)
        if op_name in ("segment", "complete"):
            models = await eng.node_assets(node.id, AssetKind.model)
            if models:
                parts = _glb_part_names(eng.abs(models[0].path))
                if parts:
                    await eng.update_asset_meta(models[0].id, {"parts": parts})
    return impl


async def op_rig(eng, node: Node) -> None:
    """Free rig-check (when rig_type=auto) -> rig. `options.rig_submitted` marks
    whether the persisted provider_task_id belongs to the rig task (vs the
    rig-check), so restarts resume the right phase."""
    opts = dict(node.options)
    rig_type = opts.get("rig_type", "auto")

    if node.provider_task_id and not opts.get("rig_submitted"):
        # persisted id is a rig-check task from a previous attempt; start over
        await eng.update_node(node.id, provider_task_id=None, progress=0)
        node = await eng.get_node(node.id)

    if node.provider_task_id:            # resuming the submitted rig task
        result = await _run_tripo(eng, node, "animations/rig", {})
    else:
        if rig_type == "auto":
            check = await _run_tripo_postop(eng, node, "animations/rig-check", {})
            if not check.output.get("riggable", True):
                raise RuntimeError("rig-check: model is not riggable")
            rig_type = check.output.get("rig_type") or "biped"
            await eng.update_node(
                node.id, provider_task_id=None, progress=0,
                options={**opts, "rig_type_resolved": rig_type})
            node = await eng.get_node(node.id)
        payload = clean_generic_options("rig", opts)
        payload["rig_type"] = rig_type
        if payload.get("model", "auto") == "auto":
            # v1.0 retargets bipeds much more cleanly (verified); v2.5 is
            # required for non-humanoid rig types.
            payload["model"] = "v1.0-20240301" if rig_type == "biped" else "v2.5-20260210"

        async def mark_submitted(task_id: str):
            await eng.update_node(node.id, provider="tripo", provider_task_id=task_id,
                                  options={**node.options, "rig_submitted": True})

        parent = await eng.get_node(node.parent_id)
        input_val, _ = await _model_input(eng, parent)
        result = await get_tripo().run_task(
            "animations/rig", {**payload, "input": input_val},
            on_submit=mark_submitted,
            on_progress=lambda p: eng.update_node(node.id, progress=p),
        )
        await eng.update_node(node.id, credits=result.credits)
    await _archive_model_outputs(eng, node, result,
                                 model_ext=opts.get("out_format", "glb"))


async def op_rescale(eng, node: Node) -> None:
    """Local uniform rescale to correct a mesh's absolute size — free, instant,
    no provider call. target_size sets the largest bounding-box dimension (in
    whatever units you want, e.g. metres); scale_factor multiplies directly."""
    from .meshinfo import glb_bounds, wrap_scale

    parent = await eng.get_node(node.parent_id)
    models = await eng.node_assets(parent.id, AssetKind.model)
    glbs = [a for a in models if (a.meta.get("format") or "glb") in ("glb", "gltf")]
    if not glbs:
        raise RuntimeError("rescale needs a GLB/GLTF parent (convert an FBX node first)")
    src = eng.abs(glbs[0].path)
    cur = glb_bounds(src)
    if not cur or cur["largest"] <= 0:
        raise RuntimeError("could not measure the parent mesh")

    opts = node.options
    if opts.get("scale_factor"):
        factor = float(opts["scale_factor"])
    elif opts.get("target_size"):
        factor = float(opts["target_size"]) / cur["largest"]
    else:
        raise RuntimeError("set target_size (largest dimension) or scale_factor")

    dst = eng.node_dir(node.project_id, node.id) / "model.glb"
    new_bounds = wrap_scale(src, dst, factor)
    await eng.add_asset(node, AssetKind.model, dst,
                        {"format": "glb", "bounds": new_bounds,
                         "scale_factor": round(factor, 6)})


async def op_fuse(eng, node: Node) -> None:
    """Merge selected segmented parts into fewer parts — free, instant, no provider
    call. options.groups is a list of part-name lists; each list collapses into one
    part (translations baked into vertices), everything else is left as-is. A single
    list may be passed as options.parts for convenience. Use the lasso/legend in the
    viewer to build the groups without hand-picking 60+ names."""
    from .meshinfo import glb_fuse

    parent = await eng.get_node(node.parent_id)
    models = await eng.node_assets(parent.id, AssetKind.model)
    glbs = [a for a in models if (a.meta.get("format") or "glb") in ("glb", "gltf")]
    if not glbs:
        raise RuntimeError("fuse needs a GLB/GLTF parent (segment a mesh first)")

    opts = node.options
    groups = opts.get("groups")
    if not groups and opts.get("parts"):
        groups = [opts["parts"]]
    # Forgive the obvious flat shape: groups=["a","b","c"] means ONE group.
    # (People reasonably type the list of names and only learn about the
    # list-of-lists nesting from the error — accept both.)
    if groups and all(isinstance(g, str) for g in groups):
        groups = [groups]
    groups = [[str(p) for p in g] for g in (groups or []) if g and len(g) >= 2]
    if not groups:
        raise RuntimeError(
            'fuse needs part names to merge. Easiest: options.parts=["tripo_part_0","tripo_part_1"] '
            "merges those into one part. For several independent merges use "
            'options.groups=[["a","b"],["c","d"]] — each inner list becomes one part. '
            "Part names are in the model asset's meta.parts (or the viewer's parts legend).")

    src = eng.abs(glbs[0].path)
    dst = eng.node_dir(node.project_id, node.id) / "model.glb"
    res = glb_fuse(src, dst, groups)
    if not res.get("fused"):
        raise RuntimeError("no parts matched the given names — nothing fused")
    await eng.add_asset(node, AssetKind.model, dst,
                        {"format": "glb", "bounds": res.get("bounds"),
                         "parts": res.get("parts"), "fused": res["fused"]})


async def op_drop(eng, node: Node) -> None:
    """Delete named parts from a segmented mesh — free, instant, no provider
    call. The counterpart to fuse: segmentation often reveals a floating scrap
    that should simply not exist (the case people were solving with a
    download → Blender → re-import detour). options.parts lists the part names
    to remove; everything else passes through byte-identical."""
    from .meshinfo import glb_drop

    parent = await eng.get_node(node.parent_id)
    models = await eng.node_assets(parent.id, AssetKind.model)
    glbs = [a for a in models if (a.meta.get("format") or "glb") in ("glb", "gltf")]
    if not glbs:
        raise RuntimeError("drop needs a GLB/GLTF parent (segment a mesh first)")

    parts = [str(p) for p in (node.options.get("parts") or []) if p]
    if not parts:
        raise RuntimeError("drop needs options.parts — the part names to delete")

    src = eng.abs(glbs[0].path)
    dst = eng.node_dir(node.project_id, node.id) / "model.glb"
    res = glb_drop(src, dst, parts)
    if not res.get("dropped"):
        raise RuntimeError("no parts matched the given names — nothing deleted")
    if not res.get("parts"):
        raise RuntimeError("refusing: dropping these parts would leave an empty mesh")
    await eng.add_asset(node, AssetKind.model, dst,
                        {"format": "glb", "bounds": res.get("bounds"),
                         "parts": res.get("parts"), "dropped": res["dropped"]})


async def op_import_model(eng, node: Node) -> None:
    # Asset is attached by the upload router before scheduling; nothing to do.
    assets = await eng.node_assets(node.id, AssetKind.model)
    if not assets:
        raise RuntimeError("import node has no uploaded model asset")


OP_IMPLS = {
    OpType.ref_set: op_ref_set,
    OpType.image_gen: op_image_gen,
    OpType.image_edit: op_image_edit,
    OpType.split: op_split,
    OpType.mesh_gen: op_mesh_gen,
    OpType.image_to_multiview: op_image_to_multiview,
    OpType.texture: _generic_postop("texture", "models/texture"),
    OpType.retopo: _generic_postop("retopo", "mesh/decimate"),
    OpType.segment: _generic_postop("segment", "mesh/segment"),
    OpType.complete: _generic_postop("complete", "mesh/complete"),
    OpType.rig: op_rig,
    OpType.retarget: _generic_postop("retarget", "animations/retarget"),
    OpType.convert: _generic_postop("convert", "models/convert"),
    OpType.rescale: op_rescale,
    OpType.fuse: op_fuse,
    OpType.drop: op_drop,
    OpType.import_model: op_import_model,
}
