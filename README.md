# orrery

Reference images + prompts → 4-view turnaround (gpt-image-2 via WaveSpeed) → 3D mesh
(Tripo multiview) → texture / retopo / rig / animate / convert — all stored as an
**append-only version tree**: every retry is a new sibling branch, every prior branch
stays instantly switchable, nothing is ever overwritten.

## Run

```bash
# server (serves API + built UI on :8420)
cd server && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8420

# UI dev mode (optional, hot reload on :5173, proxies /api)
cd web && npm run dev

# rebuild UI for production serving
cd web && npm run build
```

Keys live in `.env` at the repo root (`WAVESPEED_API_KEY`, `TRIPO_API_KEY`).
Useful env vars: `MOCK_APIS=1` (offline fixtures), `DATA_DIR`, `WAVESPEED_MAX_CONCURRENCY`
(default 2 = Bronze tier; raise to ~300 after any WaveSpeed top-up), `TRIPO_MAX_CONCURRENCY`.

## Concepts

- **Project**: prompt + a version tree of nodes. References live IN the tree:
  a `ref_set` node holds reference images (add/remove/duplicate to branch a different
  set); `image_gen` under a ref_set generates from those refs, at the root it's pure
  text-to-image; `image_edit` is img2img on any image node with its own prompt.
- **Node** = one operation (`ref_set`, `image_gen`, `image_edit`, `split`, `mesh_gen`,
  `texture`, `retopo`, `segment`, `complete`, `rig`, `retarget`, `convert`,
  `image_to_multiview`, `import_model`) applied to its parent's output, with a full
  options snapshot. Prompt assembly for image ops: subject + optional `character`
  suffix (T-pose clause, editable) + optional grid `contract` (editable).
- **Retry** = new sibling (optionally tweaked options). **Branch switching** = click a node.
- **n > 1** = parallel sibling candidates (separate provider requests).
- **Star** marks winners; chains with `select: "starred"` pause until a human/agent stars one.
- **Chain** = several steps in one call, walking down the tree (`select: "first" | "starred"`).
- Every provider output is archived on disk immediately (provider URLs expire);
  Tripo post-ops chain by `task_id` with automatic fallback to re-uploading the archived GLB.
- **Exception**: `retarget` accepts ONLY the `task_id` of a Tripo rig task (verified: file
  input → error 1004). Hand-edited rigs can't re-enter Tripo's preset animations — export
  rigged FBX with `spec: "mixamo"` and animate in Blender/Mixamo instead. Run retargets
  while the rig task is fresh.
- The `image_gen` `contract` option is the boilerplate appended to your prompt (the 4-pane
  layout + a strict T-pose clause for characters, which Tripo's rigger expects). Edit it
  per-node in the generate dialog.

## API (full docs at /docs)

| Endpoint | Purpose |
|---|---|
| `POST /api/quick` (`?wait=true`) | one call: prompt → split → textured mesh (auto-select) |
| `POST /api/projects` / `GET /api/projects/{id}/tree` | projects + full tree |
| `POST /api/projects/{id}/refs` | upload reference images |
| `POST /api/projects/{id}/nodes` | branch: `{op, parent_id, options, n}` |
| `POST /api/nodes/{id}/retry` | new sibling(s), merged options |
| `POST /api/nodes/{id}/chain` | run `[{op, options, n, select}, ...]` from a node |
| `PATCH /api/nodes/{id}` | star / archive / note |
| `GET /api/nodes/{id}/screenshots?count=8&size=1024` | headless turntable PNGs (for agents) |
| `GET /api/assets/{id}/file` | any archived file (image/model) |
| `GET /api/ops` | option catalog for every op (drives UI forms + agent discovery) |

Example — mesh with options, 3 candidates, off a split node:

```bash
curl -X POST localhost:8420/api/projects/$PID/nodes -H 'Content-Type: application/json' -d '{
  "op": "mesh_gen", "parent_id": "'$SPLIT'", "n": 3,
  "options": {"model": "v3.1-20260211", "texture_quality": "detailed",
               "geometry_quality": "detailed", "face_limit": 120000}
}'
```

Option validity is enforced per model version (e.g. `quad`/`geometry_quality` are
v3.0+-only and are stripped for v2.5; P1 has its own allowlist).

## Tests

```bash
cd server && .venv/bin/python -m pytest tests/ -q
```

Mock mode E2E: `MOCK_APIS=1 DATA_DIR=/tmp/artpipe .venv/bin/python -m uvicorn app.main:app --port 8420`

## Layout

```
server/app/
  clients/     wavespeed.py, tripo.py (+ mocks, fixtures)
  pipeline/    engine.py (node+chain executor, restart-resumable), ops.py,
               prompts.py (4-pane grid contract), tripo_options.py (option catalog)
  services/    splitter.py, renderer.py (Playwright + vendored three.js)
  routers/     projects, nodes, assets, screenshots, quick
web/           React + react-three-fiber UI
data/          projects/<id>/nodes/<id>/... (all archived outputs) + pipeline.db
```
