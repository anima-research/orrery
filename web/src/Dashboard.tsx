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
  const [recent, setRecent] = useState<any[]>([]);
  const [userTotals, setUserTotals] = useState<any[]>([]);
  const [ownerFilter, setOwnerFilter] = useState<string | null>(null);

  const load = () => api.listProjects().then(setProjects).catch(console.error);
  useEffect(() => {
    load();
    api.health().then(setHealth).catch(() => {});
    api.me().then((u) => {
      setUser(u);
      if (u?.admin) {
        api.adminRecent(48).then(setRecent).catch(() => {});
        api.adminUsers().then(setUserTotals).catch(() => {});
      }
    }).catch(() => {});
  }, []);

  const owners = [...new Set(projects.map((p) => p.owner_name || "legacy"))];
  const visibleProjects = ownerFilter
    ? projects.filter((p) => (p.owner_name || "legacy") === ownerFilter)
    : projects;

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

        {user?.admin && recent.length > 0 && (
          <>
            <h2>All activity <span style={{ fontSize: 12, color: "var(--text-dim)" }}>(admin)</span></h2>
            <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 8, marginBottom: 10 }}>
              {recent.filter((r) => r.thumb_asset).map((r) => (
                <a
                  key={r.node_id}
                  href={`#/p/${r.project_id}`}
                  title={`${r.op_type} · ${r.project_name} · ${r.owner_name}\n${r.created_at}`}
                  style={{ flexShrink: 0, textDecoration: "none", color: "var(--text-dim)", textAlign: "center", fontSize: 10 }}
                >
                  <img
                    src={`/api/assets/${r.thumb_asset}/file`}
                    style={{
                      width: 84, height: 84, objectFit: "cover", borderRadius: 8,
                      border: `1px solid ${r.status === "failed" ? "var(--red)" : "var(--border)"}`,
                      display: "block",
                    }}
                    alt=""
                  />
                  {r.owner_name}
                </a>
              ))}
            </div>
            {userTotals.length > 1 && (
              <div className="row" style={{ marginBottom: 16, fontSize: 12, color: "var(--text-dim)", gap: 14, flexWrap: "wrap" }}>
                {userTotals.map((t) => (
                  <span key={t.owner}>
                    <b style={{ color: "var(--text)" }}>{t.owner}</b> {t.projects}p/{t.nodes}n · ${t.cost_usd?.toFixed(2)} + {t.credits}cr
                  </span>
                ))}
              </div>
            )}
          </>
        )}

        <h2>Projects</h2>
        {user?.admin && owners.length > 1 && (
          <div className="row" style={{ marginBottom: 10, gap: 6, flexWrap: "wrap" }}>
            <button
              className="badge"
              style={{ borderColor: ownerFilter === null ? "var(--accent)" : "var(--border)" }}
              onClick={() => setOwnerFilter(null)}
            >
              everyone
            </button>
            {owners.map((o) => (
              <button
                key={o}
                className="badge"
                style={{ borderColor: ownerFilter === o ? "var(--accent)" : "var(--border)" }}
                onClick={() => setOwnerFilter(ownerFilter === o ? null : o)}
              >
                {o}
              </button>
            ))}
          </div>
        )}
        {visibleProjects.map((p) => (
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
        {visibleProjects.length === 0 && <div style={{ color: "var(--text-dim)" }}>No projects{ownerFilter ? ` for ${ownerFilter}` : " yet"}.</div>}
      </div>
    </>
  );
}
