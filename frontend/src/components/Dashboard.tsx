import { useEffect, useState } from "react";
import { api } from "../api";
import { Bar, QualityBadge } from "./Badges";

const TYPE_LABEL: Record<string, string> = { requirement: "Requirements", story: "User stories", module: "Modules", api: "APIs", entity: "Entities", test: "Tests", risk: "Risks" };

export default function Dashboard({ projectId, refreshKey }: { projectId: number; refreshKey: number }) {
  const [d, setD] = useState<any>(null);
  useEffect(() => { api.dashboard(projectId).then(setD); }, [projectId, refreshKey]);
  if (!d) return <p className="muted">Loading…</p>;
  const q = d.quality ?? {};

  return (
    <div className="grid">
      <div className="grid cols-4">
        <div className="card kpi"><div className="label">Blueprint quality</div><div className="value">{q.score ?? "—"}</div><QualityBadge score={q.score} /></div>
        <div className="card kpi"><div className="label">Delivery progress</div><div className="value">{d.progress.percent}%</div>
          <Bar value={d.progress.percent} ok /><div className="small muted">{d.progress.done} / {d.progress.deliverables} stories, APIs & tests done</div></div>
        <div className="card kpi"><div className="label">Priority-weighted</div><div className="value">{d.progress.priority_weighted_percent}%</div>
          <div className="small muted">must = 3 · should = 2 · could = 1</div></div>
        <div className="card kpi"><div className="label">Needs attention</div><div className="value">{d.stale_items}</div>
          <div className="small muted">items flagged by change impact · {d.findings_by_severity.error ?? 0} errors, {d.findings_by_severity.warning ?? 0} warnings</div></div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Quality breakdown</h2>
          {(["coverage", "consistency", "clarity", "linkage"] as const).map((k) => (
            <div key={k} style={{ marginBottom: ".6rem" }}>
              <div className="row small"><span style={{ textTransform: "capitalize" }}>{k}</span><span className="spacer" /><b>{q[k]}%</b></div>
              <Bar value={q[k] ?? 0} ok={(q[k] ?? 0) >= 90} />
            </div>
          ))}
          <p className="small muted" style={{ margin: 0 }}>
            ML backend: {q.ml_backend} · self-check iterations: {q.iterations?.length ?? 0} · auto-repaired: {q.auto_repaired ?? 0}
          </p>
        </div>
        <div className="card">
          <h2>Blueprint contents</h2>
          <table>
            <thead><tr><th>Type</th><th>Total</th><th>Done</th><th>Approved</th><th>Stale</th></tr></thead>
            <tbody>
              {Object.keys(TYPE_LABEL).filter((t) => d.by_type[t]).map((t) => (
                <tr key={t}><td>{TYPE_LABEL[t]}</td><td>{d.by_type[t].total}</td><td>{d.by_type[t].done}</td><td>{d.by_type[t].approved}</td>
                  <td>{d.by_type[t].stale ? <span className="badge warn">{d.by_type[t].stale}</span> : 0}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Requirement progress</h2>
          <div className="grid" style={{ gap: ".5rem", maxHeight: 420, overflow: "auto" }}>
            {d.requirements.map((r: any) => (
              <div key={r.key}>
                <div className="row small"><span className="badge key">{r.key}</span><span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.title}</span>
                  <span className="badge">{r.priority}</span><b>{r.progress}%</b></div>
                <Bar value={r.progress} ok={r.progress === 100} />
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <h2>Top risks</h2>
          <table>
            <thead><tr><th>Risk</th><th>L×I</th><th>Mitigation</th></tr></thead>
            <tbody>
              {d.top_risks.map((r: any) => (
                <tr key={r.key}><td><span className="badge key">{r.key}</span> {r.title}</td>
                  <td><span className={`badge ${r.exposure >= 15 ? "err" : r.exposure >= 9 ? "warn" : ""}`}>{r.exposure}</span></td>
                  <td className="small muted">{r.mitigation}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
