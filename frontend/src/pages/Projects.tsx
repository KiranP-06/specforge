import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type ProjectSummary } from "../api";
import { useSession } from "../App";
import { QualityBadge, StatusBadge } from "../components/Badges";

export default function Projects() {
  const { user } = useSession();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [meta, setMeta] = useState<{ llm_provider: string; ml_backend: string; version: string } | null>(null);
  const canEdit = user?.role !== "reviewer";

  useEffect(() => {
    api.projects().then(setProjects).catch((e) => setError(e.message));
    api.meta().then(setMeta).catch(() => {});
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      const p = await api.createProject(name, description, "");
      navigate(`/projects/${p.id}`);
    } catch (err) { setError((err as Error).message); }
  }

  return (
    <div className="container grid">
      <div className="row">
        <h1>Projects</h1>
        <span className="spacer" />
        {meta && <span className="small muted">v{meta.version} · generator: <b>{meta.llm_provider}</b> · ML: <b>{meta.ml_backend}</b></span>}
      </div>
      {error && <div className="alert err">{error}</div>}
      {canEdit && (
        <form className="card row" onSubmit={create}>
          <input placeholder="New project name" value={name} onChange={(e) => setName(e.target.value)} required style={{ flex: "1 1 220px", width: "auto" }} />
          <input placeholder="One-line description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} style={{ flex: "2 1 280px", width: "auto" }} />
          <button className="primary">Create project</button>
        </form>
      )}
      {projects === null ? <p className="muted">Loading…</p> : projects.length === 0 ? (
        <div className="card muted">No projects yet. Create one, paste a brief and generate its blueprint.</div>
      ) : (
        <div className="grid cols-2">
          {projects.map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="card" style={{ color: "inherit", textDecoration: "none" }}>
              <div className="row"><h2 style={{ margin: 0 }}>{p.name}</h2><span className="spacer" /><QualityBadge score={p.quality_score} /></div>
              <p className="muted small" style={{ margin: ".35rem 0" }}>{p.description || "—"}</p>
              <div className="row small">
                <StatusBadge status={p.status} />
                {p.baseline_version > 0 && <span className="badge">baseline v{p.baseline_version}</span>}
                <span className="spacer" />
                <span className="muted">updated {new Date(p.updated_at).toLocaleString()}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
