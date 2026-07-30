import type { Chain, OpCatalog, Project, Tree, TreeNode } from "./types";

let redirecting = false;
async function j<T>(res: Response): Promise<T> {
  if (res.status === 401 && !redirecting) {
    // not logged in: bounce to the archipelago home node (once)
    redirecting = true;
    try {
      const cfg = await fetch("/api/auth/config").then((r) => r.json());
      if (cfg.enabled && cfg.login_url) {
        window.location.href = cfg.login_url;
        await new Promise(() => {}); // never resolves; we're navigating away
      }
    } catch {
      /* fall through to the error below */
    }
    redirecting = false;
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body.slice(0, 300)}`);
  }
  return res.json();
}

export const api = {
  health: () => fetch("/api/health").then((r) => j<any>(r)),
  me: () => fetch("/api/auth/me").then((r) => j<any>(r)),
  logout: () => fetch("/api/auth/logout", { method: "POST" }).then((r) => j<any>(r)),
  opCatalog: () => fetch("/api/ops").then((r) => j<OpCatalog>(r)),

  listProjects: () => fetch("/api/projects").then((r) => j<Project[]>(r)),
  createProject: (name: string, prompt: string) =>
    fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, prompt }),
    }).then((r) => j<Project>(r)),
  getProject: (id: string) => fetch(`/api/projects/${id}`).then((r) => j<Project>(r)),
  getTree: (id: string, includeArchived = false) =>
    fetch(`/api/projects/${id}/tree?include_archived=${includeArchived}`).then((r) => j<Tree>(r)),
  uploadRef: (projectId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/projects/${projectId}/refs`, { method: "POST", body: fd }).then((r) => j<any>(r));
  },
  importModel: (projectId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/projects/${projectId}/import`, { method: "POST", body: fd }).then((r) => j<TreeNode>(r));
  },

  createNodes: (projectId: string, op: string, parentId: string | null, options: Record<string, any>, n = 1) =>
    fetch(`/api/projects/${projectId}/nodes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op, parent_id: parentId, options, n }),
    }).then((r) => j<TreeNode[]>(r)),
  retryNode: (nodeId: string, options: Record<string, any>, n = 1) =>
    fetch(`/api/nodes/${nodeId}/retry?n=${n}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    }).then((r) => j<TreeNode[]>(r)),
  patchNode: (nodeId: string, patch: { starred?: boolean; archived?: boolean; note?: string }) =>
    fetch(`/api/nodes/${nodeId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => j<TreeNode>(r)),
  cancelNode: (nodeId: string) => fetch(`/api/nodes/${nodeId}/cancel`, { method: "POST" }).then((r) => j<any>(r)),
  startChain: (nodeId: string, specs: Chain["specs"]) =>
    fetch(`/api/nodes/${nodeId}/chain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ specs }),
    }).then((r) => j<Chain>(r)),
  cancelChain: (chainId: string) => fetch(`/api/chains/${chainId}/cancel`, { method: "POST" }).then((r) => j<any>(r)),

  quick: (body: Record<string, any>) =>
    fetch("/api/quick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<any>(r)),

  deleteAsset: (assetId: string) =>
    fetch(`/api/assets/${assetId}`, { method: "DELETE" }).then((r) => j<any>(r)),
  uploadNodeRef: (nodeId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/nodes/${nodeId}/refs`, { method: "POST", body: fd }).then((r) => j<any>(r));
  },
  duplicateNode: (nodeId: string) =>
    fetch(`/api/nodes/${nodeId}/duplicate`, { method: "POST" }).then((r) => j<TreeNode>(r)),

  sendToEidoverse: (nodeId: string, asAvatar: boolean, name?: string, height?: number) =>
    fetch(`/api/nodes/${nodeId}/send-to-eidoverse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ as_avatar: asAvatar, name, height }),
    }).then((r) => j<any>(r)),

  screenshots: (nodeId: string, count = 8, size = 1024) =>
    fetch(`/api/nodes/${nodeId}/screenshots?count=${count}&size=${size}`).then((r) => j<any>(r)),
};

export const fileUrl = (assetId: string) => `/api/assets/${assetId}/file`;
