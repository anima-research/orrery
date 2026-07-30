import { useEffect, useState } from "react";
import { api } from "./api";
import type { Project } from "./types";

export function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<any>(null);
  const [user, setUser] = useState<any>(null);

  const load = () => api.listProjects().then(setProjects).catch(console.error);
  useEffect(() => {
    load();
    api.health().then(setHealth).catch(() => {});
    api.me().then(setUser).catch(() => {});
  }, []);

  const create = async (quick: boolean) => {
    if (!prompt.trim() && !name.trim()) return;
    setBusy(true);
    try {
      if (quick) {
        const res = await api.quick({ prompt, name: name || undefined });
        window.location.hash = `#/p/${res.project_id}`;
      } else {
        const p = await api.createProject(name || prompt.slice(0, 40), prompt);
        window.location.hash = `#/p/${p.id}`;
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="topbar">
        <h1>orrery</h1>
        <span className="spacer" />
        <a href="/agents.md" target="_blank" className="badge" style={{ textDecoration: "none" }}>
          🤖 agent API guide
        </a>
        <a href="/docs" target="_blank" className="badge" style={{ textDecoration: "none" }}>
          OpenAPI
        </a>
        {health && (
          <span className="badge">
            {health.mock ? "MOCK MODE" : "live"} · ws:{health.keys?.wavespeed ? "✓" : "✗"} tripo:
            {health.keys?.tripo ? "✓" : "✗"}
          </span>
        )}
        {user?.auth_enabled && (
          <span className="badge" title={user.sub}>
            👤 {user.name}
            {user.admin ? " (admin)" : ""}{" "}
            <a
              style={{ color: "var(--accent)", cursor: "pointer" }}
              onClick={() => api.logout().then(() => window.location.reload())}
            >
              logout
            </a>
          </span>
        )}
      </div>
      <div className="dashboard">
        <div className="new-project">
          <div className="row">
            <input
              style={{ flex: 1 }}
              placeholder="Project name (optional)"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <textarea
            rows={3}
            placeholder="Subject prompt — e.g. 'a weathered bronze owl statuette with folded wings'"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <div className="row">
            <button className="primary" disabled={busy} onClick={() => create(false)}>
              Create project
            </button>
            <button disabled={busy || !prompt.trim()} onClick={() => create(true)}>
              ⚡ Quick: prompt → textured model
            </button>
            <span className="badge" title="Quick runs image_gen → split → mesh_gen automatically">
              one call, auto-select
            </span>
          </div>
        </div>

        <h2>Projects</h2>
        {projects.map((p) => (
          <div key={p.id} className="project-card" onClick={() => (window.location.hash = `#/p/${p.id}`)}>
            <div style={{ flex: 1 }}>
              <div>
                {p.name}
                {p.shared && <span className="badge" style={{ marginLeft: 8 }}>shared</span>}
              </div>
              <div className="meta">
                {p.owner_name ? `${p.owner_name} · ` : ""}
                {p.prompt || "no prompt"}
              </div>
            </div>
            <div className="meta">
              {p.node_count} nodes · ${p.cost_usd?.toFixed(2)} + {p.credits}cr
            </div>
          </div>
        ))}
        {projects.length === 0 && <div style={{ color: "var(--text-dim)" }}>No projects yet.</div>}
      </div>
    </>
  );
}
