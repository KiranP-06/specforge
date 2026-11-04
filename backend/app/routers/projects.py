import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import Float, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..metrics import EXPORTS
from ..models import Baseline, Finding, Item, Job, Link, Project, User
from ..schemas import (
    BaselineIn,
    BaselineOut,
    FindingOut,
    JobOut,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    ProjectSummary,
)
from ..security import get_current_user, require_roles
from ..services import exporter, graph, ingest, nlp, storage
from ..worker import dispatch

log = logging.getLogger("specforge.projects")
router = APIRouter(prefix="/api", tags=["projects"])
EDITORS = ("analyst",)
REVIEWERS = ("reviewer",)


def get_project(project_id: int, db: Session) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(Project).order_by(Project.updated_at.desc())).all()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITORS))):
    p = Project(name=body.name, description=body.description, brief_text=ingest.normalise(body.brief_text), owner_id=user.id)
    db.add(p)
    db.commit()
    return p


@router.get("/projects/{project_id}", response_model=ProjectOut)
def read_project(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return get_project(project_id, db)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectPatch, db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITORS))):
    p = get_project(project_id, db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, ingest.normalise(v) if k == "brief_text" else v)
    db.commit()
    return p


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITORS))):
    p = get_project(project_id, db)
    if user.role != "admin" and p.owner_id != user.id:
        raise HTTPException(403, "Only the owner or an admin can delete a project")
    db.delete(p)
    db.commit()


@router.post("/projects/{project_id}/brief", response_model=ProjectOut)
async def upload_brief(project_id: int, file: UploadFile | None = File(default=None), text: str | None = Form(default=None),
                       db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITORS))):
    p = get_project(project_id, db)
    if file is not None:
        content = await file.read()
        if len(content) > get_settings().max_upload_mb * 1024 * 1024:
            raise HTTPException(413, "File too large")
        try:
            p.brief_text = ingest.extract_text(file.filename or "brief.txt", content)
        except ingest.UnsupportedFile as exc:
            raise HTTPException(415, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - corrupt documents
            raise HTTPException(422, f"Could not read file: {exc}") from exc
        p.brief_filename = file.filename
        p.brief_storage_key = storage.save(f"uploads/{p.id}", file.filename or "brief", content, file.content_type or "application/octet-stream")
    elif text:
        p.brief_text, p.brief_filename = ingest.normalise(text), None
    else:
        raise HTTPException(400, "Provide a file or text")
    if not p.brief_text.strip():
        raise HTTPException(422, "No readable text found in the brief")
    db.commit()
    return p


@router.post("/projects/{project_id}/generate", response_model=JobOut, status_code=202)
def generate(project_id: int, background: BackgroundTasks, db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITORS))):
    p = get_project(project_id, db)
    if not p.brief_text.strip():
        raise HTTPException(400, "Add a brief before generating")
    job = Job(project_id=p.id, kind="generate", status="queued", stage="Queued")
    p.status = "generating"
    db.add(job)
    db.commit()
    dispatch("generate", job.id, background)
    return job


@router.post("/projects/{project_id}/check", response_model=JobOut, status_code=202)
def run_checks(project_id: int, background: BackgroundTasks, repair: bool = True, db: Session = Depends(get_db),
               _: User = Depends(require_roles(*EDITORS, *REVIEWERS))):
    p = get_project(project_id, db)
    job = Job(project_id=p.id, kind="check", status="queued", stage="Queued", result={"repair": repair})
    db.add(job)
    db.commit()
    dispatch("check", job.id, background)
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def read_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
def list_jobs(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(Job).where(Job.project_id == project_id).order_by(Job.id.desc()).limit(20)).all()


@router.get("/projects/{project_id}/findings", response_model=list[FindingOut])
def findings(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    order = {"error": 0, "warning": 1, "info": 2}
    rows = db.scalars(select(Finding).where(Finding.project_id == project_id)).all()
    return sorted(rows, key=lambda f: (order.get(f.severity, 3), f.kind, f.id))


@router.get("/projects/{project_id}/trace")
def trace(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    get_project(project_id, db)
    return graph.trace_matrix(db, project_id)


@router.get("/projects/{project_id}/graph")
def graph_view(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    items = db.scalars(select(Item).where(Item.project_id == project_id)).all()
    links = db.scalars(select(Link).where(Link.project_id == project_id)).all()
    return {
        "nodes": [{"id": i.id, "key": i.key, "type": i.type, "title": i.title, "stale": i.stale, "status": i.status} for i in items],
        "edges": [{"id": l.id, "source": l.source_id, "target": l.target_id, "relation": l.relation} for l in links],
    }


@router.get("/projects/{project_id}/dashboard")
def dashboard(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    p = get_project(project_id, db)
    items = db.scalars(select(Item).where(Item.project_id == project_id)).all()
    by_type: dict[str, dict[str, int]] = {}
    for i in items:
        t = by_type.setdefault(i.type, {"total": 0, "todo": 0, "in_progress": 0, "done": 0, "blocked": 0,
                                        "approved": 0, "rejected": 0, "stale": 0})
        t["total"] += 1
        t[i.status] = t.get(i.status, 0) + 1
        if i.review_state in ("approved", "rejected"):
            t[i.review_state] += 1
        t["stale"] += int(i.stale)
    deliverable = [i for i in items if i.type in ("story", "api", "test")]
    done = sum(i.status == "done" for i in deliverable)
    weights = {"must": 3, "should": 2, "could": 1, "wont": 0}
    reqs = [i for i in items if i.type == "requirement"]
    trace_rows = {r["id"]: r for r in graph.trace_matrix(db, project_id)}
    status_of = {i.key: i.status for i in items}
    req_progress = []
    for r in reqs:
        row = trace_rows.get(r.id, {})
        linked = row.get("storys", []) + row.get("tests", [])
        pct = round(100 * sum(status_of.get(k) == "done" for k in linked) / len(linked)) if linked else 0
        req_progress.append({"key": r.key, "title": r.title, "priority": r.data.get("priority"), "progress": pct})
    wsum = sum(weights.get(r.data.get("priority"), 1) for r in reqs) or 1
    weighted = sum(weights.get(r["priority"], 1) * r["progress"] for r in req_progress) / wsum
    sev: dict[str, int] = {}
    for f in db.scalars(select(Finding).where(Finding.project_id == project_id)):
        sev[f.severity] = sev.get(f.severity, 0) + 1
    risks = sorted(({"key": i.key, "title": i.title, **i.data} for i in items if i.type == "risk"),
                   key=lambda r: -r.get("exposure", 0))
    return {
        "project": {"id": p.id, "name": p.name, "status": p.status, "baseline_version": p.baseline_version},
        "quality": p.quality_breakdown, "by_type": by_type,
        "progress": {"deliverables": len(deliverable), "done": done,
                     "percent": round(100 * done / len(deliverable), 1) if deliverable else 0.0,
                     "priority_weighted_percent": round(weighted, 1)},
        "requirements": req_progress, "findings_by_severity": sev, "top_risks": risks[:5],
        "stale_items": sum(i.stale for i in items),
    }


@router.get("/projects/{project_id}/similar")
def similar(project_id: int, q: str, limit: int = 5, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Semantic search over requirements (pgvector cosine distance on PostgreSQL)."""
    vec = nlp.embed([q])[0]
    if db.bind.dialect.name == "postgresql":
        dist = Item.embedding.op("<=>", return_type=Float)(vec)  # pgvector cosine distance
        rows = db.execute(select(Item, dist.label("d")).where(Item.project_id == project_id, Item.type == "requirement",
                                                              Item.embedding.isnot(None)).order_by(dist).limit(limit)).all()
        return [{"key": i.key, "title": i.title, "similarity": round(1 - float(d), 3)} for i, d in rows]
    reqs = db.scalars(select(Item).where(Item.project_id == project_id, Item.type == "requirement")).all()
    scored = sorted(((nlp.cosine(vec, r.embedding or nlp.embed([r.title])[0]), r) for r in reqs), key=lambda x: -x[0])
    return [{"key": r.key, "title": r.title, "similarity": round(s, 3)} for s, r in scored[:limit]]


@router.post("/projects/{project_id}/baselines", response_model=BaselineOut, status_code=201)
def create_baseline(project_id: int, body: BaselineIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*REVIEWERS))):
    p = get_project(project_id, db)
    items = db.scalars(select(Item).where(Item.project_id == project_id)).all()
    if not items:
        raise HTTPException(400, "Nothing to baseline — generate a blueprint first")
    blocking = [i.key for i in items if i.review_state == "rejected"]
    if blocking:
        raise HTTPException(409, f"Rejected items must be fixed first: {', '.join(blocking[:10])}")
    ids = {i.id: i.key for i in items}
    snapshot = {
        "items": {i.key: {"type": i.type, "title": i.title, "description": i.description, "data": i.data, "version": i.version} for i in items},
        "links": [[ids[l.source_id], ids[l.target_id], l.relation] for l in db.scalars(select(Link).where(Link.project_id == project_id))],
    }
    p.baseline_version += 1
    p.status = "baselined"
    for i in items:
        if i.review_state == "draft":
            i.review_state = "approved"
        i.stale, i.stale_reason = False, None
    b = Baseline(project_id=p.id, version=p.baseline_version, snapshot=snapshot, quality_score=p.quality_score,
                 approved_by=user.id, note=body.note)
    db.add(b)
    db.commit()
    return b


@router.get("/projects/{project_id}/baselines", response_model=list[BaselineOut])
def list_baselines(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(Baseline).where(Baseline.project_id == project_id).order_by(Baseline.version.desc())).all()


@router.get("/projects/{project_id}/diff")
def diff(project_id: int, version: int | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Compare the current blueprint with a baseline (latest by default)."""
    q = select(Baseline).where(Baseline.project_id == project_id)
    q = q.where(Baseline.version == version) if version else q.order_by(Baseline.version.desc())
    b = db.scalars(q.limit(1)).first()
    if not b:
        raise HTTPException(404, "No baseline yet")
    old = b.snapshot["items"]
    cur = {i.key: i for i in db.scalars(select(Item).where(Item.project_id == project_id))}
    added = sorted(k for k in cur if k not in old)
    removed = sorted(k for k in old if k not in cur)
    changed = sorted(k for k in cur if k in old and (cur[k].title != old[k]["title"] or cur[k].description != old[k]["description"]
                                                     or cur[k].data != old[k]["data"]))
    return {"baseline_version": b.version, "added": added, "removed": removed, "changed": changed}


@router.get("/projects/{project_id}/export/{fmt}")
def export(project_id: int, fmt: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if fmt not in exporter.EXPORTERS:
        raise HTTPException(400, f"Format must be one of {sorted(exporter.EXPORTERS)}")
    p = get_project(project_id, db)
    fn, media = exporter.EXPORTERS[fmt]
    content = fn(db, p)
    EXPORTS.labels(fmt).inc()
    ext = {"jira": "csv", "github": "json"}.get(fmt, fmt)
    suffix = {"jira": "_jira", "github": "_github_issues"}.get(fmt, "")
    filename = f"{p.name.replace(' ', '_')}_blueprint{suffix}.{ext}"
    try:
        storage.save(f"exports/{p.id}", filename, content, media)
    except Exception as exc:  # noqa: BLE001 - archiving the export must not block the download
        log.warning("could not archive export for project %s: %s", p.id, exc)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
