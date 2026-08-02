import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ModelViewer } from "./ModelViewer";
import type { Asset, OpCatalog, Tree, TreeNode } from "./types";

/** Which ops can branch off a node, by what the node produces. */
const CHILD_OPS: Record<string, string[]> = {
  ref_set: ["image_gen"],
  image_gen: ["image_edit", "split", "mesh_gen", "image_to_multiview"],
  image_edit: ["image_edit", "split", "mesh_gen", "image_to_multiview"],
  split: ["mesh_gen"],
  image_to_multiview: ["mesh_gen"],
  mesh_gen: ["texture", "retopo", "segment", "rig", "convert"],
  texture: ["retopo", "segment", "rig", "convert"],
  retopo: ["texture", "rig", "convert"],
  segment: ["complete"],
  complete: ["texture", "rig", "convert"],
  rig: ["retarget", "convert"],
  retarget: ["convert"],
  convert: [],
  import_model: ["texture", "retopo", "segment", "rig", "convert", "image_to_multiview"],
};

const MODEL_OPS = new Set(["mesh_gen", "texture", "retopo", "complete", "rig", "retarget", "convert", "import_model", "segment"]);

const VIEWABLE = new Set(["glb", "gltf", "fbx"]);

/** Viewer for viewable formats; download card for the rest (usdz/stl/3mf/obj). */
function ModelPane({ asset }: { asset: Asset }) {
  const fmt = (asset.meta.format ?? "glb").toLowerCase();
  if (!VIEWABLE.has(fmt)) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100%", color: "var(--text-dim)", fontSize: 13, textAlign: "center" }}>
        <div>
          .{fmt} — no in-browser preview
          <div style={{ marginTop: 10 }}>
            <a href={`/api/assets/${asset.id}/file`} download><button>Download {fmt.toUpperCase()}</button></a>
          </div>
        </div>
      </div>
    );
  }
  return <ModelViewer url={`/api/assets/${asset.id}/file`} format={fmt} />;
}

/** Segment-node panel: pick parts, close their holes via mesh/complete. */
function CloseHolesPanel({
  node,
  parts,
  onRefresh,
  onSelect,
}: {
  node: TreeNode;
  parts: string[];
  onRefresh: () => void;
  onSelect: (id: string) => void;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState("ai_completion");
  const [busy, setBusy] = useState(false);

  const launch = async () => {
    setBusy(true);
    try {
      const opts: Record<string, any> = { completion_mode: mode };
      if (picked.size > 0 && picked.size < parts.length) opts.part_names = [...picked];
      const nodes = await api.createNodes(node.project_id, "complete", node.id, opts);
      onRefresh();
      onSelect(nodes[0].id);
    } catch (e: any) {
      alert(`complete: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="section">
      <h3>Close holes (mesh completion)</h3>
      {parts.length > 0 ? (
        <div className="row" style={{ gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
          {parts.map((p) => (
            <label key={p} style={{ display: "flex", gap: 4, alignItems: "center", fontSize: 12 }}>
              <input
                type="checkbox"
                checked={picked.has(p)}
                onChange={() =>
                  setPicked((prev) => {
                    const next = new Set(prev);
                    next.has(p) ? next.delete(p) : next.add(p);
                    return next;
                  })
                }
              />
              {p}
            </label>
          ))}
        </div>
      ) : (
        <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 8 }}>
          no named parts detected in this GLB — completion will apply to everything
        </div>
      )}
      <div className="row">
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="ai_completion">ai_completion (50cr, plausible geometry)</option>
          <option value="quick_cap">quick_cap (30cr, flat caps)</option>
        </select>
        <button className="primary" disabled={busy} onClick={launch}>
          {picked.size === 0 || picked.size === parts.length
            ? "Close holes on all parts"
            : `Close holes on ${picked.size} part${picked.size > 1 ? "s" : ""}`}
        </button>
        <span style={{ fontSize: 11, color: "var(--text-dim)" }}>
          tip: use the viewer's “parts” toggle to see what's what
        </span>
      </div>
    </div>
  );
}

/** Default pane layout of the grid contract — mirrors server GRID_LAYOUT. */
const DEFAULT_LAYOUT: Record<string, [number, number]> = {
  front: [0, 0], left: [1, 0], back: [0, 1], right: [1, 1],
};
const VIEW_ORDER = ["front", "left", "back", "right"];

/** Relabel the four views of a split node — applying creates a NEW sibling
 * split with the permuted pane mapping (the original stays intact). */
function RelabelViews({
  node,
  views,
  onRefresh,
  onSelect,
  onZoom,
}: {
  node: TreeNode;
  views: Asset[];
  onRefresh: () => void;
  onSelect: (id: string) => void;
  onZoom: (url: string) => void;
}) {
  // labels[current] = what this image should be called
  const [labels, setLabels] = useState<Record<string, string>>(
    () => Object.fromEntries(VIEW_ORDER.map((v) => [v, v]))
  );
  const [busy, setBusy] = useState(false);
  const changed = VIEW_ORDER.some((v) => labels[v] !== v);
  const isPermutation = new Set(Object.values(labels)).size === 4;

  const effLayout: Record<string, [number, number]> = {
    ...DEFAULT_LAYOUT,
    ...(node.options.mapping ?? {}),
  };

  const apply = async (assignment: Record<string, string>) => {
    // new label -> pane coords of the image that currently carries the old label
    const mapping: Record<string, [number, number]> = {};
    for (const [oldLabel, newLabel] of Object.entries(assignment)) {
      mapping[newLabel] = effLayout[oldLabel];
    }
    setBusy(true);
    try {
      const twins = await api.retryNode(node.id, { mapping });
      onRefresh();
      onSelect(twins[0].id);
    } finally {
      setBusy(false);
    }
  };

  const swapLR = () =>
    apply({ front: "front", back: "back", left: "right", right: "left" });

  return (
    <>
      <div className="img-grid">
        {VIEW_ORDER.map((v) => {
          const a = views.find((x) => x.meta.view === v);
          if (!a) return null;
          return (
            <div key={v}>
              <img
                src={`/api/assets/${a.id}/file`}
                style={{ maxWidth: 160 }}
                onClick={() => onZoom(`/api/assets/${a.id}/file`)}
                alt=""
              />
              <div className="lbl">
                <select
                  value={labels[v]}
                  style={{ padding: "2px 6px", fontSize: 11 }}
                  title="what this image actually shows"
                  onChange={(e) => setLabels((p) => ({ ...p, [v]: e.target.value }))}
                >
                  {VIEW_ORDER.map((o) => (
                    <option key={o} value={o}>
                      {o === v ? o : `${o} (was ${v})`}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          );
        })}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button disabled={busy} onClick={swapLR} title="most common fix: mirrored side views">
          ⇄ Swap left/right
        </button>
        {changed && (
          <button
            className="primary"
            disabled={busy || !isPermutation}
            title={isPermutation ? "creates a relabeled sibling split" : "each label must be used exactly once"}
            onClick={() => apply(labels)}
          >
            {isPermutation ? "Apply relabel (new sibling)" : "labels must be unique"}
          </button>
        )}
      </div>
    </>
  );
}

export function NodeInspector({
  node,
  tree,
  ops,
  compare,
  onCompare,
  onBranch,
  onRefresh,
  onSelect,
}: {
  node: TreeNode;
  tree: Tree;
  ops: OpCatalog;
  compare: TreeNode | null;
  onCompare: (id: string) => void;
  onBranch: (op: string, parentId: string | null, presets?: Record<string, any>) => void;
  onRefresh: () => void;
  onSelect: (id: string) => void;
}) {
  const [note, setNote] = useState(node.note);
  const [lightbox, setLightbox] = useState<string | null>(null);
  const [shots, setShots] = useState<string[]>([]);
  const [shotsBusy, setShotsBusy] = useState(false);
  const refInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setNote(node.note);
    setShots([]);
  }, [node.id]);

  const modelAsset = node.assets.find((a) => a.kind === "model");
  const compareModel = compare?.assets.find((a) => a.kind === "model");
  const views = node.assets.filter((a) => a.kind === "view");
  const grid = node.assets.find((a) => a.kind === "grid");
  const render = node.assets.find((a) => a.kind === "render");
  const childOps = CHILD_OPS[node.op_type] ?? [];
  const running = node.status === "running" || node.status === "pending";

  const takeShots = async () => {
    setShotsBusy(true);
    try {
      const res = await api.screenshots(node.id, 8, 768);
      setShots(res.screenshots);
    } catch (e: any) {
      alert(`screenshots failed: ${e.message}`);
    } finally {
      setShotsBusy(false);
    }
  };

  return (
    <div>
      <div className="section row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 17 }}>
            {node.op_type} <span style={{ color: "var(--text-dim)", fontWeight: 400 }}>#{node.id}</span>
          </h2>
          <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 2 }}>
            {node.status}
            {running && ` · ${node.progress}%`}
            {node.provider && ` · ${node.provider}`}
            {node.credits > 0 && ` · ${node.credits}cr`}
            {node.cost_usd > 0 && ` · $${node.cost_usd.toFixed(3)}`}
          </div>
        </div>
        <div className="row">
          {running && (
            <button className="danger" onClick={() => api.cancelNode(node.id).then(onRefresh)}>
              Cancel
            </button>
          )}
          <button onClick={() => api.patchNode(node.id, { starred: !node.starred }).then(onRefresh)}>
            {node.starred ? "★ Unstar" : "☆ Star"}
          </button>
          <button onClick={() => api.patchNode(node.id, { archived: !node.archived }).then(onRefresh)}>
            {node.archived ? "Unarchive" : "Archive"}
          </button>
          <button
            className="primary"
            onClick={() => onBranch(node.op_type, node.parent_id, { ...node.options, __retry_node: node.id })}
          >
            ↻ Retry (tweak)
          </button>
        </div>
      </div>

      {node.error && (
        <div className="section">
          <div className="error-box">{node.error}</div>
        </div>
      )}

      {/* reference set */}
      {node.op_type === "ref_set" && (
        <div className="section">
          <h3>Reference images ({node.assets.filter((a) => a.kind === "ref").length})</h3>
          <div className="img-grid">
            {node.assets
              .filter((a) => a.kind === "ref")
              .map((a) => (
                <div key={a.id} style={{ position: "relative" }}>
                  <img src={`/api/assets/${a.id}/file`} style={{ maxWidth: 180 }} onClick={() => setLightbox(`/api/assets/${a.id}/file`)} alt="" />
                  <button
                    title="remove reference"
                    style={{ position: "absolute", top: 4, right: 4, padding: "1px 7px", background: "rgba(0,0,0,0.6)", borderRadius: 12 }}
                    onClick={async () => {
                      await api.deleteAsset(a.id);
                      onRefresh();
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={() => refInput.current?.click()}>+ Add images</button>
            <button
              title="new sibling set with copies of these refs — tweak it freely"
              onClick={async () => {
                const twin = await api.duplicateNode(node.id);
                onRefresh();
                onSelect(twin.id);
              }}
            >
              ⑂ Duplicate set
            </button>
          </div>
          <input
            ref={refInput}
            type="file"
            hidden
            accept="image/*"
            multiple
            onChange={async (e) => {
              for (const f of Array.from(e.target.files ?? [])) await api.uploadNodeRef(node.id, f);
              e.target.value = "";
              onRefresh();
            }}
          />
        </div>
      )}

      {/* 3D preview */}
      {modelAsset && (
        <div className="section">
          <h3>
            Model {compare && compareModel ? `— comparing with ${compare.op_type} #${compare.id}` : ""}
          </h3>
          <div className={`viewer-box ${compare && compareModel ? "compare" : ""}`}>
            {compare && compareModel ? (
              <>
                <div><ModelPane asset={compareModel} /></div>
                <div><ModelPane asset={modelAsset} /></div>
              </>
            ) : (
              <ModelPane asset={modelAsset} />
            )}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={() => onCompare(node.id)}>
              {compare?.id === node.id ? "Unpin compare" : "Pin for compare"}
            </button>
            <button disabled={shotsBusy} onClick={takeShots}>
              {shotsBusy ? "Rendering…" : "Turntable screenshots"}
            </button>
            <a href={`/api/assets/${modelAsset.id}/file`} download>
              <button>Download {(modelAsset.meta.format ?? "glb").toUpperCase()}</button>
            </a>
            {(modelAsset.meta.format ?? "glb") === "glb" && (
              <>
                <button
                  title="upload this GLB into eidoverse-worlds as a world object"
                  onClick={async () => {
                    const name = window.prompt("Object name for the eidoverse catalog\n(empty = project name):", "");
                    if (name === null) return; // cancelled
                    try {
                      const r = await api.sendToEidoverse(node.id, false, name || undefined);
                      alert(`sent to eidoverse: ${r.path}\n(spawn it in-world via the asset verb)`);
                      onRefresh();
                    } catch (e: any) {
                      alert(`eidoverse: ${e.message}`);
                    }
                  }}
                >
                  🌍 → Eidoverse
                </button>
                {["rig", "retarget"].includes(node.op_type) && (
                  <button
                    title="convert to VRM 1.0 (glb2vrm) and upload as a wearable avatar"
                    onClick={async () => {
                      const name = window.prompt("Avatar name:", `art_${node.id.slice(0, 6)}`);
                      if (!name) return;
                      const h = window.prompt("Height in meters (blank = default):", "");
                      try {
                        const r = await api.sendToEidoverse(node.id, true, name, h ? parseFloat(h) : undefined);
                        alert(`avatar uploaded: ${r.name}\nwear it with ?avatar=${r.name}`);
                        onRefresh();
                      } catch (e: any) {
                        alert(`eidoverse: ${e.message}`);
                      }
                    }}
                  >
                    🧍 → Eidoverse avatar
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {shots.length > 0 && (
        <div className="section">
          <h3>Turntable</h3>
          <div className="img-grid">
            {shots.map((s) => (
              <img key={s} src={s} style={{ maxWidth: 130 }} onClick={() => setLightbox(s)} alt="" />
            ))}
          </div>
        </div>
      )}

      {/* image previews */}
      {grid && (
        <div className="section">
          <h3>Generated grid</h3>
          <div className="img-grid">
            <img src={`/api/assets/${grid.id}/file`} style={{ maxWidth: 380 }} onClick={() => setLightbox(`/api/assets/${grid.id}/file`)} alt="" />
          </div>
        </div>
      )}
      {views.length > 0 && (
        <div className="section">
          <h3>Views</h3>
          {node.op_type === "split" && node.status === "completed" ? (
            <RelabelViews node={node} views={views} onRefresh={onRefresh} onSelect={onSelect} onZoom={setLightbox} />
          ) : (
            <div className="img-grid">
              {["front", "left", "back", "right"].map((v) => {
                const a = views.find((x) => x.meta.view === v);
                return a ? (
                  <div key={v}>
                    <img src={`/api/assets/${a.id}/file`} style={{ maxWidth: 160 }} onClick={() => setLightbox(`/api/assets/${a.id}/file`)} alt="" />
                    <div className="lbl">{v}</div>
                  </div>
                ) : null;
              })}
            </div>
          )}
        </div>
      )}
      {render && !modelAsset && (
        <div className="section">
          <h3>Render</h3>
          <div className="img-grid">
            <img src={`/api/assets/${render.id}/file`} style={{ maxWidth: 300 }} onClick={() => setLightbox(`/api/assets/${render.id}/file`)} alt="" />
          </div>
        </div>
      )}

      {/* segmentation: close holes on selected parts */}
      {node.op_type === "segment" && node.status === "completed" && modelAsset && (
        <CloseHolesPanel node={node} parts={modelAsset.meta.parts ?? []} onRefresh={onRefresh} onSelect={onSelect} />
      )}

      {/* branch actions */}
      {node.status === "completed" && childOps.length > 0 && (
        <div className="section">
          <h3>Branch a new step from this node</h3>
          <div className="row">
            {childOps.map((op) => (
              <button key={op} onClick={() => onBranch(op, node.id)}>
                + {op}
              </button>
            ))}
            {node.op_type === "image_gen" && (
              <button
                className="primary"
                title="split + mesh_gen in one go"
                onClick={async () => {
                  await api.startChain(node.id, [
                    { op: "split", options: {}, n: 1, select: "first" },
                    { op: "mesh_gen", options: { texture: true, pbr: true }, n: 1, select: "first" },
                  ]);
                  onRefresh();
                }}
              >
                ⚡ Auto → mesh
              </button>
            )}
          </div>
        </div>
      )}

      {/* metadata */}
      <div className="section">
        <h3>Options used</h3>
        <div className="kv">
          {Object.entries(node.options)
            .filter(([k]) => k !== "__retry_node")
            .map(([k, v]) => (
              <span key={k} style={{ display: "contents" }}>
                <span className="k">{k}</span>
                <span>{JSON.stringify(v)}</span>
              </span>
            ))}
          {node.provider_task_id && (
            <>
              <span className="k">provider task</span>
              <span style={{ wordBreak: "break-all" }}>{node.provider_task_id}</span>
            </>
          )}
        </div>
      </div>

      <div className="section">
        <h3>Note</h3>
        <div className="row">
          <input
            style={{ flex: 1 }}
            value={note}
            placeholder="free-form note…"
            onChange={(e) => setNote(e.target.value)}
          />
          <button
            disabled={note === node.note}
            onClick={() => api.patchNode(node.id, { note }).then(onRefresh)}
          >
            Save
          </button>
        </div>
      </div>

      {lightbox && (
        <div className="lightbox" onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="" />
        </div>
      )}
    </div>
  );
}
