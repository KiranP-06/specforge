import { useEffect, useState } from "react";
import { api, type Baseline } from "../api";
import { useSession } from "../App";

export default function BaselinesPanel({ projectId, onChanged }: { projectId: number; onChanged: () => void }) {
  const { user } = useSession();
  const canReview = user?.role === "admin" || user?.role === "reviewer";
  const [baselines, setBaselines] = useState<Baseline[]>([]);
  const [diff, setDiff] = useState<{ baseline_version: number; added: string[]; removed: string[]; changed: string[] } | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = () => {
    api.baselines(projectId).then((b) => { setBaselines(b); if (b.length) api.diff(projectId).then(setDiff).catch(() => setDiff(null)); });
  };
  useEffect(load, [projectId]);

  async function approve() {
    setError("");
    try { await api.baseline(projectId, note); setNote(""); load(); onChanged(); }
    catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="grid cols-2" style={{ alignItems: "start" }}>
      <div className="card grid">
        <h2>Approve & baseline</h2>
        <p className="small muted" style={{ margin: 0 }}>A baseline freezes the approved blueprint (all items and links). Draft items are approved; rejected items block the baseline. Later edits show up as a diff and propagate change-impact flags.</p>
        {canReview ? (
          <div className="row"><input placeholder="Baseline note (e.g. 'Signed off with client')" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, width: "auto" }} />
            <button className="primary" onClick={approve}>Create baseline</button></div>
        ) : <div className="alert warn small">Only reviewers and admins can create baselines.</div>}
        {error && <div className="alert err small">{error}</div>}
        <table>
          <thead><tr><th>Version</th><th>Quality</th><th>Note</th><th>Created</th></tr></thead>
          <tbody>{baselines.map((b) => <tr key={b.id}><td>v{b.version}</td><td>{b.quality_score ?? "—"}</td><td>{b.note}</td><td className="small">{new Date(b.created_at).toLocaleString()}</td></tr>)}</tbody>
        </table>
      </div>
      <div className="card grid">
        <h2>Changes since baseline {diff ? `v${diff.baseline_version}` : ""}</h2>
        {!diff ? <p className="muted small">No baseline yet.</p> : (
          (["added", "changed", "removed"] as const).map((k) => (
            <div key={k}><b style={{ textTransform: "capitalize" }}>{k}</b> <span className="muted">({diff[k].length})</span>
              <div className="row" style={{ marginTop: ".25rem" }}>{diff[k].map((key) => <span key={key} className="badge key">{key}</span>)}{diff[k].length === 0 && <span className="muted small">none</span>}</div></div>
          ))
        )}
      </div>
    </div>
  );
}
