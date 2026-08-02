import type { ReactElement } from "react";
import type { Tree, TreeNode } from "./types";

const OP_ICONS: Record<string, string> = {
  ref_set: "🗂",
  image_edit: "🪄",
  image_gen: "🖼",
  split: "✂️",
  mesh_gen: "🧊",
  image_to_multiview: "🔄",
  texture: "🎨",
  retopo: "🕸",
  segment: "🧩",
  complete: "🩹",
  rig: "🦴",
  retarget: "🏃",
  convert: "📦",
  rescale: "📐",
  import_model: "📥",
};

function thumbFor(node: TreeNode): string | null {
  const order = ["screenshot", "render", "grid", "view", "ref"];
  for (const kind of order) {
    const a = node.assets.find((a) => a.kind === kind);
    if (a) return `/api/assets/${a.id}/file`;
  }
  return null;
}

function NodeCard({
  node,
  selected,
  onSelect,
  onStar,
}: {
  node: TreeNode;
  selected: boolean;
  onSelect: (id: string) => void;
  onStar: (n: TreeNode) => void;
}) {
  const thumb = thumbFor(node);
  const opts = Object.entries(node.options)
    .filter(([k, v]) => v !== null && v !== "" && v !== false && !["prompt", "rig_submitted"].includes(k))
    .slice(0, 3)
    .map(([k, v]) => (v === true ? k : `${k}=${v}`))
    .join(" · ");
  return (
    <div
      className={`tnode-card ${selected ? "selected" : ""} ${node.status === "failed" ? "failed" : ""}`}
      onClick={() => onSelect(node.id)}
    >
      {thumb ? <img className="thumb" src={thumb} alt="" /> : <div className="thumb" style={{ display: "grid", placeItems: "center" }}>{OP_ICONS[node.op_type] ?? "•"}</div>}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="op">
          {OP_ICONS[node.op_type]} {node.op_type}
          {node.archived ? " (archived)" : ""}
        </div>
        <div className="sub" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {node.status === "failed" ? node.error?.slice(0, 60) : opts || node.id}
        </div>
      </div>
      <button
        className={`star-btn ${node.starred ? "on" : ""}`}
        title="star (chains with select=starred pick starred nodes)"
        onClick={(e) => {
          e.stopPropagation();
          onStar(node);
        }}
      >
        {node.starred ? "★" : "☆"}
      </button>
      <span className={`status-dot ${node.status}`} title={node.status} />
      {node.status === "running" && (
        <div className="progress-bar" style={{ width: `${Math.max(4, node.progress)}%` }} />
      )}
    </div>
  );
}

export function TreePanel({
  tree,
  selectedId,
  onSelect,
  onStar,
}: {
  tree: Tree;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onStar: (n: TreeNode) => void;
}) {
  const byParent = new Map<string | null, TreeNode[]>();
  for (const n of tree.nodes) {
    const key = n.parent_id ?? null;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(n);
  }

  const render = (parentId: string | null): ReactElement[] =>
    (byParent.get(parentId) ?? []).map((n) => (
      <div className="tnode" key={n.id}>
        <NodeCard node={n} selected={n.id === selectedId} onSelect={onSelect} onStar={onStar} />
        {(byParent.get(n.id)?.length ?? 0) > 0 && (
          <div className="tnode-children">{render(n.id)}</div>
        )}
      </div>
    ));

  const roots = render(null);
  return (
    <div>
      {roots.length > 0 ? roots : <div style={{ color: "var(--text-dim)", padding: 12 }}>No nodes yet — hit “+ Generate views”.</div>}
    </div>
  );
}
