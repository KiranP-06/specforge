import { useEffect, useState } from "react";
import { api, type TraceRow } from "../api";

const COLS: { key: keyof TraceRow; label: string; required?: (r: TraceRow) => boolean }[] = [
  { key: "storys", label: "Stories", required: (r) => r.kind === "FR" },
  { key: "modules", label: "Modules", required: (r) => r.kind === "FR" },
  { key: "apis", label: "APIs" },
  { key: "entitys", label: "Entities" },
  { key: "tests", label: "Tests", required: () => true },
  { key: "risks", label: "Risks" },
];

export default function TraceMatrix({ projectId }: { projectId: number }) {
  const [rows, setRows] = useState<TraceRow[] | null>(null);
  useEffect(() => { api.trace(projectId).then(setRows); }, [projectId]);
  if (!rows) return <p className="muted">Loading…</p>;
  const covered = rows.filter((r) => COLS.every((c) => !c.required?.(r) || (r[c.key] as string[]).length > 0)).length;

  return (
    <div className="grid">
      <p className="small muted" style={{ margin: 0 }}>Requirement → story → module → API → entity → test → risk. Red cells are required links that are missing. {covered}/{rows.length} requirements fully covered.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Requirement</th><th>Kind</th>{COLS.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td style={{ minWidth: 260 }}><span className="badge key">{r.key}</span> {r.stale && <span className="badge warn">stale</span>}<div className="small">{r.title}</div></td>
                <td><span className="badge">{r.kind}</span></td>
                {COLS.map((c) => {
                  const v = r[c.key] as string[];
                  return <td key={c.key} className={`cell-keys ${c.required?.(r) && v.length === 0 ? "missing" : ""}`}>{v.join(", ") || "—"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
