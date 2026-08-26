export interface Project {
  id: string;
  name: string;
  prompt: string;
  owner_sub?: string | null;
  owner_name?: string;
  shared?: boolean;
  created_at: string;
  node_count?: number;
  cost_usd?: number;
  credits?: number;
}

export interface Asset {
  id: string;
  node_id: string | null;
  project_id: string;
  kind: "ref" | "grid" | "view" | "model" | "render" | "screenshot";
  path: string;
  meta: Record<string, any>;
}

export type NodeStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface TreeNode {
  id: string;
  project_id: string;
  parent_id: string | null;
  op_type: string;
  options: Record<string, any>;
  group_id: string | null;
  provider: string | null;
  provider_task_id: string | null;
  status: NodeStatus;
  progress: number;
  error: string | null;
  cost_usd: number;
  credits: number;
  starred: boolean;
  archived: boolean;
  note: string;
  created_at: string;
  updated_at: string;
  assets: Asset[];
}

export interface Chain {
  id: string;
  project_id: string;
  anchor_node_id: string | null;
  specs: { op: string; options: Record<string, any>; n: number; select: string }[];
  cursor: number;
  status: "running" | "waiting_selection" | "completed" | "failed" | "cancelled";
  error: string | null;
}

export interface Tree {
  nodes: TreeNode[];
  refs: Asset[];
  chains: Chain[];
}

export interface FieldSpec {
  type: "enum" | "bool" | "int" | "float" | "text" | "json";
  enum?: string[];
  default?: any;
  min?: number;
  max?: number;
  desc?: string;
  /** Per-model form overrides: keyed by the op's `model` value; fields the
   *  chosen model doesn't take carry hidden:true (server derives this from
   *  the same allowlists its option cleaner enforces). */
  per_model?: Record<string, Partial<FieldSpec> & { hidden?: boolean }>;
}

export interface OpSpec {
  provider: string;
  endpoint?: string;
  credits?: string;
  fields: Record<string, FieldSpec>;
}

export type OpCatalog = Record<string, OpSpec>;
