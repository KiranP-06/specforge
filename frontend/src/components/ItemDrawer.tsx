import { useEffect, useState } from "react";
import { api, type Comment, type Impact, type Item, type Status, type Version } from "../api";
import { useSession } from "../App";
import { StatusBadge } from "./Badges";

export default function ItemDrawer({ item, onChanged, onSelect }: { item: Item; onChanged: () => void; onSelect: (id: number) => void }) {
  const { user } = useSession();
  const canEdit = user?.role === "admin" || user?.role === "analyst";
  const canReview = user?.role === "admin" || user?.role === "reviewer";
  const [links, setLinks] = useState<{ upstream: any[]; downstream: any[] } | null>(null);
  const [impact, setImpact] = useState<Impact[] | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [description, setDescription] = useState(item.description);
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const [lastImpact, setLastImpact] = useState<Impact[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.links(item.id).then(setLinks);
    api.versions(item.id).then(setVersions);
    api.comments(item.id).then(setComments);
  }, [item.id, item.version]);

  async function save() {
    try {
      const res = await api.updateItem(item.id, { title, description, change_note: note });
      setLastImpact(res.impacted); setEditing(false); setNote(""); onChanged();
    } catch (e) { setError((e as Error).message); }
  }
  async function setStatus(status: Status) { await api.updateItem(item.id, { status }); onChanged(); }
  async function review(state: "approved" | "rejected") { await api.review(item.id, state); onChanged(); }
  async function postComment() {
    if (!comment.trim()) return;
    const c = await api.addComment(item.id, comment.trim());
    setComments((cs) => [...cs, c]); setComment("");
  }
  async function remove() {
    if (!window.confirm(`Delete ${item.key}? Dependent items will be flagged for review.`)) return;
    await api.deleteItem(item.id); onChanged();
  }

  const d = item.data ?? {};
  return (
    <div className="card grid" style={{ gap: ".85rem" }}>
      <div className="row"><span className="badge key">{item.key}</span><span className="badge">{item.type}</span><span className="muted small">v{item.version} · {item.origin}</span>
        <span className="spacer" />{canEdit && <button className="ghost danger small" onClick={remove}>Delete</button>}</div>
      {item.stale && (
        <div className="alert warn small">{item.stale_reason}
          <div className="row" style={{ marginTop: ".4rem" }}><button onClick={async () => { await api.acknowledge(item.id); onChanged(); }}>Still valid — clear flag</button></div>
        </div>
      )}
      {editing ? (
        <div className="grid" style={{ gap: ".5rem" }}>
          <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <label>Description<textarea value={description} onChange={(e) => setDescription(e.target.value)} /></label>
          <label>Change note<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why is this changing?" /></label>
          <div className="row"><button className="primary" onClick={save}>Save & propagate</button><button onClick={() => setEditing(false)}>Cancel</button></div>
        </div>
      ) : (
        <div>
          <h3>{item.title}</h3>
          {item.description && item.description !== item.title && <p className="small" style={{ margin: 0 }}>{item.description}</p>}
          {canEdit && <button style={{ marginTop: ".5rem" }} onClick={() => setEditing(true)}>Edit</button>}
        </div>
      )}
      {error && <div className="alert err small">{error}</div>}
      {lastImpact && (
        <div className={`alert ${lastImpact.length ? "warn" : "ok"} small`}>
          {lastImpact.length ? <>Change propagated: <b>{lastImpact.length}</b> dependent item(s) flagged — {lastImpact.map((i) => i.key).join(", ")}</> : "Saved. No dependent items."}
        </div>
      )}

      <Details item={item} d={d} />

      <div className="row small">
        <span>Status</span>
        <select value={item.status} onChange={(e) => setStatus(e.target.value as Status)} style={{ width: "auto" }}>
          <option value="todo">todo</option><option value="in_progress">in progress</option><option value="done">done</option><option value="blocked">blocked</option>
        </select>
        <span>Review</span><StatusBadge status={item.review_state} />
        {canReview && <><button onClick={() => review("approved")}>Approve</button><button onClick={() => review("rejected")}>Reject</button></>}
      </div>

      <section>
        <h3>Links</h3>
        {links && (["upstream", "downstream"] as const).map((dir) => links[dir].length > 0 && (
          <div key={dir} className="small" style={{ marginBottom: ".4rem" }}>
            <div className="muted">{dir === "upstream" ? "Depends on" : "Feeds into"}</div>
            <div className="row">{links[dir].map((l) => (
              <a key={l.link_id} href="#" onClick={(e) => { e.preventDefault(); onSelect(l.id); }} title={`${l.relation}: ${l.title}`}><span className="badge key">{l.key}</span></a>
            ))}</div>
          </div>
        ))}
      </section>

      <section>
        <div className="row"><h3 style={{ margin: 0 }}>Change impact</h3><span className="spacer" />
          <button className="small" onClick={() => api.impact(item.id).then(setImpact)}>Preview</button></div>
        {impact && (impact.length === 0 ? <p className="small muted">No dependent items.</p> : (
          <ul className="clean small">{impact.map((i) => <li key={i.id}><span className="badge key">{i.key}</span> <span className="muted">{i.path.join(" → ")}</span></li>)}</ul>
        ))}
      </section>

      {versions.length > 0 && (
        <section><h3>History</h3>
          <ul className="clean small">{versions.map((v) => <li key={v.id}>v{v.version} · {new Date(v.created_at).toLocaleString()} — {v.change_note || "edit"}</li>)}</ul>
        </section>
      )}

      <section>
        <h3>Comments</h3>
        <div className="grid small" style={{ gap: ".35rem" }}>
          {comments.map((c) => <div key={c.id} className="list-item" style={{ cursor: "default" }}><span>{c.body}</span><span className="muted">{new Date(c.created_at).toLocaleString()}</span></div>)}
        </div>
        <div className="row" style={{ marginTop: ".4rem" }}>
          <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add a comment…" style={{ flex: 1, width: "auto" }} onKeyDown={(e) => e.key === "Enter" && postComment()} />
          <button onClick={postComment}>Post</button>
        </div>
      </section>
    </div>
  );
}

function Details({ item, d }: { item: Item; d: Record<string, any> }) {
  if (item.type === "requirement") return <div className="row small"><span className="badge">{d.kind}</span><span className="badge">{d.category}</span><span className="badge">{d.priority}</span><span className="badge">{d.stakeholder}</span></div>;
  if (item.type === "story") return <div className="small"><b>Acceptance criteria</b><ul className="clean">{(d.acceptance_criteria ?? []).map((c: string, i: number) => <li key={i}>{c}</li>)}</ul></div>;
  if (item.type === "entity") return <table className="small"><thead><tr><th>Field</th><th>Type</th></tr></thead><tbody>{(d.fields ?? []).map((f: any) => <tr key={f.name}><td className="mono">{f.name}</td><td>{f.type}</td></tr>)}</tbody></table>;
  if (item.type === "test") return <div className="small"><span className="badge">{d.type}</span><ol className="clean">{(d.steps ?? []).map((s: string, i: number) => <li key={i}>{s}</li>)}</ol><b>Expected:</b> {d.expected}</div>;
  if (item.type === "risk") return <div className="small">Likelihood <b>{d.likelihood}</b> × Impact <b>{d.impact}</b> = <b>{d.exposure}</b><br /><b>Mitigation:</b> {d.mitigation}</div>;
  if (item.type === "api") return <div className="small mono">{d.method} {d.path}</div>;
  return null;
}
