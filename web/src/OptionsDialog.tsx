import { useMemo, useState } from "react";
import type { FieldSpec, OpSpec } from "./types";

/** Options form generated from the /api/ops field specs. */
export function OptionsDialog({
  op,
  spec,
  presets,
  projectPrompt,
  onCancel,
  onSubmit,
}: {
  op: string;
  spec?: OpSpec;
  presets?: Record<string, any>;
  projectPrompt: string;
  onCancel: () => void;
  onSubmit: (options: Record<string, any>, n: number) => Promise<void>;
}) {
  const fields = spec?.fields ?? {};
  const isRetry = !!presets?.__retry_node;

  // last-used options persist in the browser: retry presets > stored > defaults
  const initial = useMemo(() => {
    let stored: Record<string, any> = {};
    try {
      stored = JSON.parse(localStorage.getItem(`art:last:${op}`) ?? "{}");
    } catch {
      /* ignore */
    }
    const v: Record<string, any> = {};
    for (const [key, f] of Object.entries(fields)) {
      if (key === "n") continue;
      const preset = presets?.[key];
      let val = preset !== undefined ? preset : stored[key] !== undefined ? stored[key] : f.default ?? "";
      // stale enum values (e.g. from a renamed model list) fall back to the default
      if (f.type === "enum" && f.enum && !f.enum.includes(val)) val = f.default ?? f.enum[0];
      v[key] = val;
    }
    // prompt is required by the image models — surface the project prompt as a
    // real editable value instead of a hidden fallback
    if ("prompt" in fields && !v.prompt) v.prompt = projectPrompt;
    return v;
  }, [op]);

  const [values, setValues] = useState<Record<string, any>>(initial);
  const [n, setN] = useState<number>(presets?.n ?? 1);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = (k: string, v: any) => setValues((prev) => ({ ...prev, [k]: v }));

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const options: Record<string, any> = {};
      for (const [key, f] of Object.entries(fields)) {
        if (key === "n") continue;
        let v = values[key];
        if (v === "" || v === undefined || v === null) continue;
        if (f.type === "int") v = parseInt(v, 10);
        if (f.type === "float") v = parseFloat(v);
        if (f.type === "json" && typeof v === "string") {
          try {
            v = JSON.parse(v);
          } catch {
            throw new Error(`${key}: invalid JSON`);
          }
        }
        if (Number.isNaN(v)) continue;
        options[key] = v;
      }
      if ("prompt" in fields && !options.prompt?.trim()) {
        throw new Error("prompt is required — type one here (or set a project prompt)");
      }
      try {
        localStorage.setItem(`art:last:${op}`, JSON.stringify(options));
      } catch {
        /* storage full/blocked — not critical */
      }
      await onSubmit(options, n);
    } catch (e: any) {
      setErr(e.message);
      setBusy(false);
    }
  };

  const renderField = (key: string, f: FieldSpec) => {
    const v = values[key];
    switch (f.type) {
      case "enum":
        return (
          <select value={v ?? ""} onChange={(e) => set(key, e.target.value)}>
            {(f.enum ?? []).map((o) => (
              <option key={o} value={o}>
                {o === "" ? "(none)" : o}
              </option>
            ))}
          </select>
        );
      case "bool":
        return <input type="checkbox" checked={!!v} onChange={(e) => set(key, e.target.checked)} />;
      case "int":
      case "float":
        return (
          <input
            type="number"
            value={v ?? ""}
            min={f.min}
            max={f.max}
            step={f.type === "float" ? 0.01 : 1}
            placeholder={f.default == null ? "auto" : String(f.default)}
            onChange={(e) => set(key, e.target.value)}
          />
        );
      case "text":
        return (
          <textarea
            rows={(v?.length ?? 0) > 140 ? 8 : 3}
            value={v ?? ""}
            placeholder={key === "prompt" ? projectPrompt || "prompt…" : ""}
            onChange={(e) => set(key, e.target.value)}
          />
        );
      case "json":
        return (
          <input
            value={typeof v === "string" ? v : v ? JSON.stringify(v) : ""}
            placeholder="JSON (optional)"
            onChange={(e) => set(key, e.target.value)}
          />
        );
    }
  };

  const supportsN = "n" in fields || ["image_gen", "mesh_gen"].includes(op);

  return (
    <div className="dialog-backdrop" onClick={onCancel}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2>
          {isRetry ? `Retry ${op} (new sibling)` : `New ${op}`}
          {spec?.credits && <span className="badge" style={{ marginLeft: 10 }}>{spec.credits} credits</span>}
        </h2>
        <div className="form-grid">
          {Object.entries(fields)
            .filter(([k]) => k !== "n")
            .map(([key, f]) => (
              <span key={key} style={{ display: "contents" }}>
                <label title={f.desc}>{key}</label>
                {renderField(key, f)}
                {f.desc && <div className="hint">{f.desc}</div>}
              </span>
            ))}
          {supportsN && (
            <>
              <label>parallel candidates</label>
              <input type="number" min={1} max={8} value={n} onChange={(e) => setN(parseInt(e.target.value || "1", 10))} />
            </>
          )}
        </div>
        {err && <div className="error-box" style={{ marginTop: 12 }}>{err}</div>}
        <div className="actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" disabled={busy} onClick={submit}>
            {busy ? "Starting…" : n > 1 ? `Launch ${n} candidates` : "Launch"}
          </button>
        </div>
      </div>
    </div>
  );
}
