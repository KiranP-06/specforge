import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Project } from "../api";
import { useSession } from "../App";
import { QualityBadge, StatusBadge } from "../components/Badges";
import BriefPanel from "../components/BriefPanel";
import Dashboard from "../components/Dashboard";
import BlueprintPanel from "../components/BlueprintPanel";
import TraceMatrix from "../components/TraceMatrix";
import GraphView from "../components/GraphView";
import FindingsPanel from "../components/FindingsPanel";
import BaselinesPanel from "../components/BaselinesPanel";

const TABS = ["Brief", "Dashboard", "Blueprint", "Trace matrix", "Graph", "Quality", "Review & baselines"] as const;
type Tab = (typeof TABS)[number];

export default function ProjectView() {
  const id = Number(useParams().id);
  const { user } = useSession();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [tab, setTab] = useState<Tab>("Brief");
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");

  const reload = useCallback(() => {
    api.project(id).then((p) => { setProject(p); setRefreshKey((k) => k + 1); }).catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    api.project(id).then((p) => { setProject(p); if (p.quality_score != null) setTab("Dashboard"); }).catch((e) => setError(e.message));
  }, [id]);

  async function exportAs(fmt: string) {
    try { await api.download(id, fmt); } catch (e) { setError((e as Error).message); }
  }

  async function remove() {
    if (!project || !window.confirm(`Delete project "${project.name}"? This cannot be undone.`)) return;
    await api.deleteProject(project.id);
    navigate("/");
  }

  if (error && !project) return <div className="container"><div className="alert err">{error}</div></div>;
  if (!project) return <div className="container muted">Loading…</div>;
  const hasBlueprint = project.quality_score != null;

  return (
    <div className="container">
      <div className="row" style={{ marginBottom: ".75rem" }}>
        <div>
          <h1 style={{ marginBottom: ".2rem" }}>{project.name}</h1>
          <div className="row small"><StatusBadge status={project.status} /><QualityBadge score={project.quality_score} />
            {project.baseline_version > 0 && <span className="badge ok">baseline v{project.baseline_version}</span>}
            <span className="muted">{project.description}</span></div>
        </div>
        <span className="spacer" />
        {hasBlueprint && (
          <div className="row">
            <span className="small muted">Export</span>
            {["docx", "pdf", "csv", "json", "jira", "github"].map((f) => <button key={f} onClick={() => exportAs(f)}>{{ jira: "Jira CSV", github: "GitHub Issues" }[f] ?? f.toUpperCase()}</button>)}
          </div>
        )}
        {user?.role !== "reviewer" && <button className="danger ghost" onClick={remove}>Delete</button>}
      </div>
      {error && <div className="alert err" style={{ marginBottom: "1rem" }}>{error}</div>}
      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} disabled={t !== "Brief" && !hasBlueprint} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>
      {tab === "Brief" && <BriefPanel project={project} onGenerated={() => { reload(); setTab("Dashboard"); }} onSaved={setProject} />}
      {tab === "Dashboard" && <Dashboard projectId={id} refreshKey={refreshKey} />}
      {tab === "Blueprint" && <BlueprintPanel projectId={id} onChanged={reload} />}
      {tab === "Trace matrix" && <TraceMatrix projectId={id} />}
      {tab === "Graph" && <GraphView projectId={id} />}
      {tab === "Quality" && <FindingsPanel project={project} onChecked={reload} />}
      {tab === "Review & baselines" && <BaselinesPanel projectId={id} onChanged={reload} />}
    </div>
  );
}
