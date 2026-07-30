import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { NodeInspector } from "./NodeInspector";
import { TreePanel } from "./TreePanel";
import { OptionsDialog } from "./OptionsDialog";
import type { OpCatalog, Project, Tree, TreeNode } from "./types";

export function ProjectView({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [tree, setTree] = useState<Tree | null>(null);
  const [ops, setOps] = useState<OpCatalog>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareId, setCompareId] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [dialog, setDialog] = useState<{ op: string; parentId: string | null; presets?: Record<string, any> } | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

  const refresh = useCallback(() => {
    api.getTree(projectId, showArchived).then(setTree).catch(console.error);
  }, [projectId, showArchived]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch(console.error);
    api.opCatalog().then(setOps).catch(console.error);
  }, [projectId]);

  useEffect(() => {
    refresh();
    const t = setInterval(() => {
      if (!document.hidden) refresh();
    }, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  const selected: TreeNode | null = useMemo(
    () => tree?.nodes.find((n) => n.id === selectedId) ?? null,
    [tree, selectedId]
  );
  const compare: TreeNode | null = useMemo(
    () => tree?.nodes.find((n) => n.id === compareId) ?? null,
    [tree, compareId]
  );

  const activeChains = tree?.chains.filter((c) => c.status === "running" || c.status === "waiting_selection") ?? [];

  const submitDialog = async (options: Record<string, any>, n: number) => {
    if (!dialog) return;
    if (dialog.presets?.__retry_node) {
      await api.retryNode(dialog.presets.__retry_node, options, n);
    } else {
      await api.createNodes(projectId, dialog.op, dialog.parentId, options, n);
    }
    setDialog(null);
    refresh();
  };

  const newRefSet = async (files: File[] = []): Promise<string> => {
    const nodes = await api.createNodes(projectId, "ref_set", null, {}, 1);
    for (const f of files) await api.uploadNodeRef(nodes[0].id, f);
    refresh();
    setSelectedId(nodes[0].id);
    return nodes[0].id;
  };

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    const images = files.filter((f) => f.type.startsWith("image/"));
    const models = files.filter((f) => /\.(glb|gltf|fbx|obj|stl)$/i.test(f.name));
    if (images.length) {
      // drop onto a selected ref_set adds to it; otherwise a new set is created
      if (selected?.op_type === "ref_set") {
        for (const f of images) await api.uploadNodeRef(selected.id, f);
      } else {
        await newRefSet(images);
      }
    }
    for (const f of models) await api.importModel(projectId, f);
    refresh();
  };

  return (
    <div
      style={{ height: "100%" }}
      onDragEnter={(e) => {
        e.preventDefault();
        dragDepth.current += 1;
        setDragging(true);
      }}
      onDragLeave={() => {
        dragDepth.current -= 1;
        if (dragDepth.current <= 0) setDragging(false);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      {dragging && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 40, pointerEvents: "none",
            background: "rgba(110,168,254,0.12)", border: "3px dashed var(--accent)",
            display: "grid", placeItems: "center", fontSize: 18, color: "var(--accent)",
          }}
        >
          drop images → references · drop models → import
        </div>
      )}
      <div className="topbar">
        <h1 onClick={() => (window.location.hash = "")}>orrery</h1>
        <span className="crumb">/ {project?.name ?? projectId}</span>
        <span className="spacer" />
        <a href="/agents.md" target="_blank" className="badge" style={{ textDecoration: "none" }} title="API guide for agents">
          🤖
        </a>
        {project && (
          <label
            className="row"
            style={{ fontSize: 12, color: "var(--text-dim)" }}
            title="shared projects are visible (read-only) to all logged-in users"
          >
            <input
              type="checkbox"
              checked={!!project.shared}
              onChange={async (e) => {
                const p = await fetch(`/api/projects/${projectId}`, {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ shared: e.target.checked }),
                }).then((r) => r.json());
                setProject(p);
              }}
            />
            shared
          </label>
        )}
        <label className="row" style={{ fontSize: 12, color: "var(--text-dim)" }}>
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          show archived
        </label>
        <button onClick={() => importRef.current?.click()}>Import model</button>
        <button onClick={() => fileRef.current?.click()}>+ Reference set</button>
        <button
          className="primary"
          title="text-to-image at the root; branch off a ref_set to use references"
          onClick={() =>
            setDialog({
              op: "image_gen",
              parentId: selected?.op_type === "ref_set" ? selected.id : null,
            })
          }
        >
          + Generate views
        </button>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept="image/*"
          multiple
          onChange={async (e) => {
            await newRefSet(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
        <input
          ref={importRef}
          type="file"
          hidden
          accept=".glb,.gltf,.fbx,.obj,.stl"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) await api.importModel(projectId, f);
            e.target.value = "";
            refresh();
          }}
        />
      </div>

      <div className="layout">
        <div className="tree-panel">
          {activeChains.map((c) => (
            <div key={c.id} className="chain-banner">
              <span>
                ⛓ chain step {c.cursor + 1}/{c.specs.length} ({c.specs[Math.min(c.cursor, c.specs.length - 1)]?.op})
                {c.status === "waiting_selection" && " — waiting for a ★ selection"}
              </span>
              <span className="spacer" style={{ flex: 1 }} />
              <button className="danger" onClick={() => api.cancelChain(c.id).then(refresh)}>
                cancel
              </button>
            </div>
          ))}
          {tree && (
            <TreePanel
              tree={tree}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onStar={(n) => api.patchNode(n.id, { starred: !n.starred }).then(refresh)}
            />
          )}
        </div>
        <div className="inspector">
          {selected ? (
            <NodeInspector
              node={selected}
              tree={tree!}
              ops={ops}
              compare={compare}
              onCompare={(id) => setCompareId(id === compareId ? null : id)}
              onBranch={(op, parentId, presets) => setDialog({ op, parentId, presets })}
              onRefresh={refresh}
              onSelect={setSelectedId}
            />
          ) : (
            <ProjectHome tree={tree} project={project} />
          )}
        </div>
      </div>

      {dialog && (
        <OptionsDialog
          op={dialog.op}
          spec={ops[dialog.op]}
          presets={dialog.presets}
          projectPrompt={project?.prompt ?? ""}
          onCancel={() => setDialog(null)}
          onSubmit={submitDialog}
        />
      )}
    </div>
  );
}

function ProjectHome({ tree, project }: { tree: Tree | null; project: Project | null }) {
  return (
    <div>
      <div className="section">
        <h3>Project</h3>
        <div className="kv">
          <span className="k">prompt</span>
          <span>{project?.prompt || "—"}</span>
          <span className="k">nodes</span>
          <span>{tree?.nodes.length ?? 0}</span>
        </div>
      </div>
      <div className="section" style={{ color: "var(--text-dim)", fontSize: 13, lineHeight: 1.7 }}>
        Everything is a branchable node in the tree, references included:
        <br />• <b>+ Reference set</b> (or drop images anywhere) → a 🗂 ref_set node; branch <b>image_gen</b> off
        it to generate <i>from</i> those references, or duplicate the set to try a different mix.
        <br />• <b>+ Generate views</b> with nothing selected → pure text-to-image at the root.
        <br />• Any image node can branch an 🪄 <b>image_edit</b> (img2img with its own prompt).
        <br />• Retry = new sibling, nothing is ever overwritten. Star ★ winners to guide auto-chains.
      </div>
    </div>
  );
}
