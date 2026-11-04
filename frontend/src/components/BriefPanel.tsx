import { useState } from "react";
import { api, pollJob, type Job, type Project } from "../api";
import { useSession } from "../App";
import { Bar } from "./Badges";

const SAMPLE = `Students must be able to register and log in with their college email.
Students can browse the menu and filter items by category and price.
A student should be able to add items to a cart and place an order for a pickup time slot.
Students must be able to pay online using UPI through a payment gateway.
Canteen staff can view incoming orders and update the order status to preparing, ready or collected.
The system shall notify the student by email when the order is ready.
Admins can create, edit and delete menu items and set daily stock.
Students can cancel an order up to 10 minutes before the pickup slot.
Students can cancel an order at any time, even after it is ready.
The app must be fast and user-friendly on mobile phones.
Order placement must complete within 2 seconds for 95% of requests.
All passwords must be stored hashed and all traffic must use HTTPS.`;

export default function BriefPanel({ project, onGenerated, onSaved }: { project: Project; onGenerated: () => void; onSaved: (p: Project) => void }) {
  const { user } = useSession();
  const canEdit = user?.role !== "reviewer";
  const [text, setText] = useState(project.brief_text);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function upload(file: File) {
    setError(""); setBusy(true);
    try { const p = await api.uploadBrief(project.id, file); setText(p.brief_text); onSaved(p); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function generate() {
    setError(""); setBusy(true);
    try {
      if (text !== project.brief_text) onSaved(await api.uploadBrief(project.id, undefined, text));
      const started = await api.generate(project.id);
      const done = await pollJob(started.id, setJob);
      if (done.status === "succeeded") onGenerated(); else setError(done.error ?? "Generation failed");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="grid cols-2">
      <div className="card grid">
        <div className="row"><h2 style={{ margin: 0 }}>Project brief</h2><span className="spacer" />
          {project.brief_filename && <span className="badge">{project.brief_filename}</span>}</div>
        <p className="muted small" style={{ margin: 0 }}>Paste an idea, client brief, SOW or SRS — or upload a PDF, DOCX, TXT or MD file.</p>
        <textarea value={text} onChange={(e) => setText(e.target.value)} readOnly={!canEdit} style={{ minHeight: 320 }} placeholder="Describe what the software must do…" />
        {canEdit && (
          <div className="row">
            <label className="btn" style={{ display: "inline-flex", width: "auto", fontWeight: 400 }}>
              Upload file<input type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
            {!text && <button onClick={() => setText(SAMPLE)}>Use sample brief</button>}
            <span className="spacer" />
            <button className="primary" disabled={busy || !text.trim()} onClick={generate}>
              {project.quality_score != null ? "Regenerate blueprint" : "Generate blueprint"}
            </button>
          </div>
        )}
        {project.quality_score != null && canEdit && <p className="small muted" style={{ margin: 0 }}>Regenerating replaces the current draft blueprint. Baselines are kept.</p>}
        {error && <div className="alert err">{error}</div>}
      </div>
      <div className="card grid" style={{ alignContent: "start" }}>
        <h2>How generation works</h2>
        <ol className="clean small" style={{ display: "grid", gap: ".35rem" }}>
          <li><b>Understand</b> — extract requirements, stakeholders, constraints and priorities; classify FR / NFR.</li>
          <li><b>Draft</b> — the generator emits schema-validated JSON (stories, modules, APIs, entities, tests, risks); invalid drafts are sent back for repair.</li>
          <li><b>Link</b> — every item becomes a node linked to the requirement it serves.</li>
          <li><b>Self-check</b> — rule layer (coverage, orphans, vague terms) + ML layer (duplicates, contradictions); gaps are auto-repaired.</li>
          <li><b>Score</b> — a Blueprint Quality Score summarises coverage, consistency, clarity and linkage.</li>
        </ol>
        {job && (
          <div className="grid" style={{ gap: ".4rem" }}>
            <div className="row small"><b>{job.stage || job.status}</b><span className="spacer" />{job.progress}%</div>
            <Bar value={job.progress} ok={job.status === "succeeded"} />
            {job.result?.fallback_used && <div className="alert warn small">The LLM returned invalid drafts; the offline generator was used instead.</div>}
          </div>
        )}
      </div>
    </div>
  );
}
