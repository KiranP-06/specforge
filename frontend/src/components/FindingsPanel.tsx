import { useEffect, useState } from "react";
import { api, pollJob, type Finding, type Project } from "../api";
import { Bar, SeverityBadge } from "./Badges";

const EXPLAIN: Record<string, string> = {
  missing_story: "Functional requirement without a user story", missing_test: "Requirement without a test scenario",
  missing_module: "Requirement not allocated to a module", vague_term: "Unverifiable wording", unmeasurable_nfr: "NFR without a measurable threshold",
  orphan_api: "API that serves no requirement", orphan_entity: "Entity not used by any API", duplicate: "Semantic similarity above threshold",
  contradiction: "Contradiction detector (NLI cross-encoder, or heuristic in lightweight mode)", classification_mismatch: "FR/NFR classifier disagrees with label",
};

export default function FindingsPanel({ project, onChecked }: { project: Project; onChecked: () => void }) {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [busy, setBusy] = useState(false);
  const q = project.quality_breakdown;
  useEffect(() => { api.findings(project.id).then(setFindings); }, [project.id, project.quality_score]);

  async function recheck() {
    setBusy(true);
    try { const j = await api.check(project.id); await pollJob(j.id, () => {}); onChecked(); api.findings(project.id).then(setFindings); }
    finally { setBusy(false); }
  }

  return (
    <div className="grid cols-2" style={{ alignItems: "start" }}>
      <div className="card grid">
        <div className="row"><h2 style={{ margin: 0 }}>Findings</h2><span className="spacer" />
          <button className="primary" disabled={busy} onClick={recheck}>{busy ? "Checking…" : "Re-run self-check"}</button></div>
        {findings.length === 0 ? <div className="alert ok">No open findings — the blueprint is consistent.</div> : (
          <div className="table-wrap" style={{ maxHeight: "60vh" }}>
            <table>
              <thead><tr><th>Severity</th><th>Layer</th><th>Finding</th></tr></thead>
              <tbody>{findings.map((f) => (
                <tr key={f.id}><td><SeverityBadge severity={f.severity} /></td><td><span className="badge">{f.layer}</span></td>
                  <td>{f.message}<div className="small muted">{EXPLAIN[f.kind] ?? f.kind}</div></td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
      <div className="card grid">
        <h2>Blueprint Quality Score</h2>
        <div className="kpi"><div className="value">{q?.score ?? "—"}<span className="muted small"> / 100</span></div></div>
        <p className="small muted" style={{ margin: 0 }}>0.40 × coverage + 0.25 × consistency + 0.20 × clarity + 0.15 × linkage</p>
        {q && (["coverage", "consistency", "clarity", "linkage"] as const).map((k) => (
          <div key={k}><div className="row small"><span style={{ textTransform: "capitalize" }}>{k}</span><span className="spacer" />{q[k]}%</div><Bar value={q[k]} ok={q[k] >= 90} /></div>
        ))}
        {q?.iterations && (
          <div className="small"><b>Self-check loop</b>
            <ul className="clean">{q.iterations.map((it) => <li key={it.iteration}>Iteration {it.iteration}: {it.issues} issue(s), score {it.score}</li>)}</ul>
            <span className="muted">{q.auto_repaired ?? 0} item(s) auto-repaired · ML backend: {q.ml_backend}</span>
          </div>
        )}
      </div>
    </div>
  );
}
