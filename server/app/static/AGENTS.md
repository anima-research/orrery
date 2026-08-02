# orrery — Agent API Guide

You are talking to a reference-images → 3D-model pipeline. Everything a human can
do in the web UI, you can do over plain HTTP. Full OpenAPI schema: `GET /docs`
(interactive) or `GET /openapi.json`. This page is the practical guide.

## Auth (public deployments)

If `GET /api/auth/config` says `{"enabled": true}`, every `/api` call needs an
archipelago identity with the `orrery:use` scope.

**Agents — the short version:** mint one `aid1` token (lasts ~7 days), set it
as a header once, forget about auth until you see a 401:

```python
client = httpx.Client(base_url="https://orrery.animalabs.ai",
                      headers={"Authorization": f"Bearer {TOKEN}"})
```

**Minting** (once per token lifetime, NOT per call) — you must be enrolled at
the home node with the `orrery:use` scope; then `POST https://id.animalabs.ai/token`:

```jsonc
{ "id": "ed25519:<b64url of your raw 32-byte pubkey>",
  "audience": "orrery",
  "timestamp": "<ISO-8601 now, ±5 min>",
  "proof": "<b64url ed25519 signature over the exact string:
             archipelago-token|v1|id.animalabs.ai|orrery|<same timestamp>>" }
// → { "token": "aid1.…" }   reuse until it expires (401 = re-mint)
```

**Humans**: visit the login link from `/api/auth/config` → Discord → you land
on `/auth` with a 12h session cookie.

Projects are per-user: you see your own plus ones marked `shared`
(`PATCH /api/projects/{id} {"shared": true}` to publish yours read-only).
Everything you create is keyed to your durable `sub`. On local/tailnet
instances auth is usually disabled and none of this applies.

## The one concept that matters: the version tree

All state in a project is an **append-only tree of nodes**. A node = one operation
applied to its parent's output, with a full options snapshot:

```
ref_set ──▶ image_gen ──▶ split ──▶ mesh_gen ──▶ texture / retopo / rig ──▶ retarget ──▶ convert
(refs)      (4-view grid)  (4 PNGs)  (GLB)                                  (animations)   (FBX/USDZ/…)
```

- **Nothing is ever overwritten.** Retrying an op creates a *sibling* node.
  Branch different options off any node at any time; every old branch stays live.
- `n > 1` when creating nodes = parallel sibling candidates.
- **Selection = navigation**: to "pick a winner" you simply extend that node with
  children. Set `starred: true` to mark winners (auto-chains with
  `select: "starred"` wait for a star — that's the human/agent review gate).
- Node statuses: `pending → running → completed | failed | cancelled`, with
  `progress` 0–100. Poll the tree every ~2 s while work is running.

## Endpoints you'll actually use

| Action | Call |
|---|---|
| Create project | `POST /api/projects {"name", "prompt"}` |
| Read the whole tree | `GET /api/projects/{pid}/tree` → `{nodes:[{...,assets:[]}], chains:[]}` |
| Create node(s) | `POST /api/projects/{pid}/nodes {"op", "parent_id", "options", "n"}` |
| Retry (new sibling, tweaked) | `POST /api/nodes/{id}/retry?n=1` body = option overrides |
| Star / archive / note | `PATCH /api/nodes/{id} {"starred": true}` |
| Cancel | `POST /api/nodes/{id}/cancel` |
| Run several steps in one call | `POST /api/nodes/{id}/chain {"specs":[{"op","options","n","select"}]}` |
| One-call prompt→textured model | `POST /api/quick?wait=true {"prompt", "image_options", "mesh_options", "n_images", "n_meshes"}` |
| Option catalog (all ops, all fields, credit costs) | `GET /api/ops` |
| Fetch any output file | `GET /api/assets/{asset_id}/file` (asset ids come from tree nodes) |
| Add refs to a ref_set | `POST /api/nodes/{id}/refs` (multipart `file`) |
| Duplicate a ref_set | `POST /api/nodes/{id}/duplicate` |
| Import external model | `POST /api/projects/{pid}/import` (multipart `file`, glb/fbx/obj/stl) |
| **Review a mesh without a browser** | `GET /api/nodes/{id}/screenshots?count=8&size=1024` → turntable PNG URLs |
| Push to eidoverse-worlds | `POST /api/nodes/{id}/send-to-eidoverse {"as_avatar": bool, "name"?, "height"?}` — GLB nodes become world objects; rig/retarget nodes with `as_avatar: true` are converted to VRM and join the avatar roster |
| Health / mock status | `GET /api/health` |

## Ops and their key options

`GET /api/ops` is the source of truth (field types, enums, defaults, credit
costs). Summary:

- **ref_set** — container for reference images. Upload refs onto it, then branch
  `image_gen` off it. Duplicate to try a different set.
- **image_gen** — root-level = text-to-image; under a ref_set = generation guided
  by those refs. Options: `prompt`, `model` (8 models across WaveSpeed /
  OpenRouter / BFL — see enum), `resolution 0.5k|1k|2k|4k`, `quality` (gpt-image-2
  only), `aspect_ratio`, `seed` (FLUX only), `character` (bool → appends editable
  T-pose suffix; use for anything that will be rigged), `grid_contract` (bool →
  appends the 4-pane turnaround contract; keep `true` when the output feeds
  `split`), `contract` (editable contract text).
- **image_edit** — img2img on the parent node's image with its own `prompt`.
  Editing a grid keeps grid-ness.
- **split** — cuts the parent grid into `front/left/back/right.png`. Options:
  `auto_label` (default true — a Haiku vision pass reads which view is in each
  pane and permutes the crop, fixing the common left/right swap; falls back to
  the default layout if it can't read a clean 4-view set), `mapping` (explicit
  pane→view override, wins over auto_label), `trim`. The chosen source is
  recorded in `options.label_source` (`explicit` | `auto_label` | `default`).
- **mesh_gen** — Tripo →3D. Off a split (or image_to_multiview) parent: multiview
  mesh from the 4 views. Off an image node directly: single-image mesh (faster,
  no grid needed; back side is imagined by the model).
  Key options: `model` (`v3.1-20260211` best, `P1-20260311` low-poly), `texture`,
  `pbr`, `texture_quality standard|detailed|extreme`, `geometry_quality`,
  `face_limit`, `quad`, seeds. Invalid params for a model version are stripped
  automatically.
- **Absolute dimensions & rescale (IMPORTANT)** — Tripo normalizes every mesh to
  **largest bounding-box dimension = 1.0** (a mug and a house both come out "1.0"),
  unless `mesh_gen` was run with `auto_size: true`. Every GLB/GLTF model asset
  carries its real dimensions in `asset.meta.bounds` = `{size:[x,y,z], min, max,
  largest}` (model units). `/api/quick` returns the final model's bounds as
  `dimensions`. To CORRECT the size, branch a **rescale** node (local, free,
  instant): `{op:"rescale", options:{target_size: 1.7}}` sets the largest
  dimension to 1.7 (or `scale_factor` to multiply directly). The new bounds are
  on the rescale node's model asset. Do this before sending to eidoverse if the
  world expects real-world scale.
- **texture / retopo / segment / complete / rig / retarget / convert** — Tripo
  post-ops, each branched off any model-producing node. Rigging: `rig` with
  `rig_type: auto` (free riggability check picks biped/quadruped/…; model `auto`
  selects the best rig version). `retarget` needs a rig-node parent and preset
  names matching the rig version (`preset:biped:idle` for rig v1.0, `preset:idle`
  for v2.5); `animations` accepts a list — one call, many clips. `convert`
  exports FBX/USDZ/OBJ/STL/3MF.

## Recipes

Full auto, one call (blocks until done, ~5 min):
```bash
curl -X POST 'http://HOST/api/quick?wait=true' -H 'Content-Type: application/json' -d '{
  "prompt": "a bronze owl statuette",
  "image_options": {"resolution": "4k", "quality": "high"},
  "mesh_options": {"model": "v3.1-20260211", "texture": true, "pbr": true},
  "n_images": 2, "n_meshes": 2
}'
# → {project_id, chain_id, status, final_node_id, assets[...]}
```

Interactive with review (you are the reviewer):
```bash
# 1. project + generation
PID=$(curl -sX POST http://HOST/api/projects -d '{"name":"owl","prompt":"a bronze owl"}' -H 'Content-Type: application/json' | jq -r .id)
curl -sX POST http://HOST/api/projects/$PID/nodes -H 'Content-Type: application/json' \
  -d '{"op":"image_gen","options":{"character":false},"n":3}'
# 2. poll tree until image_gen nodes complete; download each grid asset and LOOK at them
curl -s http://HOST/api/projects/$PID/tree | jq '.nodes[] | {id, op_type, status, assets}'
curl -s http://HOST/api/assets/ASSET_ID/file -o grid.png
# 3. branch split + mesh off the best candidate
curl -sX POST http://HOST/api/nodes/BEST_IMAGE_NODE/chain -H 'Content-Type: application/json' \
  -d '{"specs":[{"op":"split"},{"op":"mesh_gen","options":{"texture":true,"pbr":true},"n":2,"select":"starred"}]}'
# 4. when both meshes finish, review them via turntables, star the winner:
curl -s 'http://HOST/api/nodes/MESH_NODE/screenshots?count=8&size=768'
curl -sX PATCH http://HOST/api/nodes/MESH_NODE -H 'Content-Type: application/json' -d '{"starred":true}'
# (the waiting chain resumes automatically after the star)
```

Rig + animate + export, one chain:
```bash
curl -sX POST http://HOST/api/nodes/MESH_NODE/chain -H 'Content-Type: application/json' -d '{
  "specs": [
    {"op": "rig", "options": {"rig_type": "auto"}},
    {"op": "retarget", "options": {"animations": ["preset:biped:idle", "preset:biped:walk"]}},
    {"op": "convert", "options": {"format": "FBX", "fbx_preset": "blender"}}
  ]}'
```

## Judgment guidance (what "good" looks like)

- **Grid candidates**: all four panes must show the SAME object, consistent scale,
  clean background, object fully inside each pane. Reject grids where views
  disagree (different accessories, colors) — the mesh inherits the inconsistency.
- **For riggable characters**: set `"character": true` so the T-pose suffix is
  applied; limbs must be clearly separated from the body in all views.
- **Meshes**: check the 8-angle turntable; look for fused limbs, missing back
  detail, texture seams. Retrying `mesh_gen` with a different `model_seed` is
  cheap (20 cr) relative to fixing downstream.
- **Costs**: every node records `cost_usd` (images) or `credits` (Tripo,
  1 cr = $0.01). Chains stop cleanly on failure — completed work is never lost.

## Etiquette

- Poll `GET /api/projects/{pid}/tree` at ~2 s; back off when nothing is running.
- Don't delete anything (you can't) — archive nodes you consider dead ends
  (`PATCH {"archived": true}`) and leave a `note` explaining why.
- Leave `note`s on starred winners: the human reads them.
