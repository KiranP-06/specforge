"""Export the blueprint as CSV, JSON, Jira CSV, DOCX or PDF."""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Finding, Item, Link, Project
from . import graph

SECTIONS = [
    ("stakeholder", "Stakeholders"), ("constraint", "Constraints"), ("requirement", "Requirements"),
    ("story", "User Stories"), ("module", "Modules"), ("entity", "Data Entities"), ("api", "API Endpoints"),
    ("test", "Test Scenarios"), ("risk", "Risk Register"),
]


def _items(db: Session, pid: int) -> list[Item]:
    return list(db.scalars(select(Item).where(Item.project_id == pid).order_by(Item.type, Item.key)))


def to_json(db: Session, project: Project) -> bytes:
    items = _items(db, project.id)
    ids = {i.id: i.key for i in items}
    links = db.scalars(select(Link).where(Link.project_id == project.id))
    doc = {
        "project": {"name": project.name, "description": project.description, "quality": project.quality_breakdown,
                    "baseline_version": project.baseline_version, "exported_at": datetime.now(UTC).isoformat()},
        "items": [{"key": i.key, "type": i.type, "title": i.title, "description": i.description, "data": i.data,
                   "status": i.status, "review_state": i.review_state, "version": i.version} for i in items],
        "links": [{"from": ids[l.source_id], "to": ids[l.target_id], "relation": l.relation} for l in links],
    }
    return json.dumps(doc, indent=2, default=str).encode()


def to_csv(db: Session, project: Project) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["key", "type", "title", "description", "status", "review_state", "priority", "kind", "category", "version", "stale"])
    for i in _items(db, project.id):
        w.writerow([i.key, i.type, i.title, i.description, i.status, i.review_state, i.data.get("priority", ""),
                    i.data.get("kind", ""), i.data.get("category", ""), i.version, i.stale])
    return buf.getvalue().encode()


def to_jira_csv(db: Session, project: Project) -> bytes:
    """CSV importable by Jira's external-system importer (Stories + Tasks for tests)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Summary", "Issue Type", "Description", "Priority", "Labels"])
    pr = {"must": "Highest", "should": "High", "could": "Medium", "wont": "Low"}
    for i in _items(db, project.id):
        if i.type == "story":
            ac = "\n".join(f"* {c}" for c in i.data.get("acceptance_criteria", []))
            w.writerow([i.title[:250], "Story", f"{i.key}\n\nAcceptance criteria:\n{ac}", pr.get(i.data.get("priority"), "Medium"), "specforge"])
        elif i.type == "test":
            steps = "\n".join(f"# {s}" for s in i.data.get("steps", []))
            w.writerow([i.title[:250], "Task", f"{i.key}\n{steps}\n\nExpected: {i.data.get('expected', '')}", "Medium", "specforge test"])
    return buf.getvalue().encode()


def to_github_issues(db: Session, project: Project) -> bytes:
    """JSON list of issues for scripts/import_github_issues.sh (uses `gh issue create`)."""
    issues = []
    for i in _items(db, project.id):
        d = i.data or {}
        if i.type == "story":
            ac = "\n".join(f"- [ ] {c}" for c in d.get("acceptance_criteria", []))
            issues.append({"title": f"[{i.key}] {i.title}"[:250], "labels": ["specforge", "user-story", f"priority:{d.get('priority', 'should')}"],
                           "body": f"**Story {i.key}** from SPECForge project *{project.name}*.\n\n### Acceptance criteria\n{ac}"})
        elif i.type == "test":
            steps = "\n".join(f"{n}. {s}" for n, s in enumerate(d.get("steps", []), 1))
            issues.append({"title": f"[{i.key}] {i.title}"[:250], "labels": ["specforge", "test", d.get("type", "functional")],
                           "body": f"### Steps\n{steps}\n\n### Expected\n{d.get('expected', '')}"})
    return json.dumps(issues, indent=2).encode()


def _detail_lines(i: Item) -> list[str]:
    d = i.data or {}
    if i.type == "requirement":
        return [f"Kind: {d.get('kind')} · Category: {d.get('category')} · Priority: {d.get('priority')} · Stakeholder: {d.get('stakeholder')}"]
    if i.type == "story":
        return [f"Acceptance: {c}" for c in d.get("acceptance_criteria", [])]
    if i.type == "entity":
        return ["Fields: " + ", ".join(f"{f['name']}:{f['type']}" for f in d.get("fields", []))]
    if i.type == "test":
        return [f"Step {n}: {s}" for n, s in enumerate(d.get("steps", []), 1)] + [f"Expected: {d.get('expected', '')}"]
    if i.type == "risk":
        return [f"Likelihood {d.get('likelihood')} × Impact {d.get('impact')} = {d.get('exposure')} · Mitigation: {d.get('mitigation')}"]
    return []


def to_docx(db: Session, project: Project) -> bytes:
    import docx
    from docx.shared import Pt

    doc = docx.Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.add_heading(f"{project.name} — Software Blueprint", 0)
    doc.add_paragraph(f"Generated by SPECForge · {datetime.now(UTC):%d %b %Y} · Baseline v{project.baseline_version}")
    if project.quality_breakdown:
        q = project.quality_breakdown
        doc.add_paragraph(f"Blueprint Quality Score: {q.get('score')} / 100  (coverage {q.get('coverage')}%, "
                          f"consistency {q.get('consistency')}%, clarity {q.get('clarity')}%, linkage {q.get('linkage')}%)")
    items = _items(db, project.id)
    for type_, label in SECTIONS:
        group = [i for i in items if i.type == type_]
        if not group:
            continue
        doc.add_heading(label, 1)
        for i in group:
            p = doc.add_paragraph()
            p.add_run(f"{i.key}  ").bold = True
            p.add_run(i.title)
            if i.description and i.description != i.title and type_ not in ("constraint",):
                doc.add_paragraph(i.description, style="List Bullet")
            for line in _detail_lines(i):
                doc.add_paragraph(line, style="List Bullet")
    rows = graph.trace_matrix(db, project.id)
    if rows:
        doc.add_heading("Traceability Matrix", 1)
        t = doc.add_table(rows=1, cols=5)
        t.style = "Light Grid Accent 1"
        for c, h in zip(t.rows[0].cells, ["Requirement", "Stories", "APIs", "Tests", "Risks"], strict=False):
            c.text = h
        for r in rows:
            cells = t.add_row().cells
            cells[0].text, cells[1].text = r["key"], ", ".join(r["storys"])
            cells[2].text, cells[3].text, cells[4].text = ", ".join(r["apis"]), ", ".join(r["tests"]), ", ".join(r["risks"])
    findings = list(db.scalars(select(Finding).where(Finding.project_id == project.id)))
    if findings:
        doc.add_heading("Open Quality Findings", 1)
        for f in findings:
            doc.add_paragraph(f"[{f.severity.upper()}] {f.message}", style="List Bullet")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def to_pdf(db: Session, project: Project) -> bytes:
    from html import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"{project.name} blueprint")
    story = [Paragraph(escape(f"{project.name} — Software Blueprint"), styles["Title"]),
             Paragraph(escape(f"Generated by SPECForge · {datetime.now(UTC):%d %b %Y} · Baseline v{project.baseline_version}"), styles["Normal"])]
    if project.quality_breakdown:
        q = project.quality_breakdown
        story.append(Paragraph(f"<b>Blueprint Quality Score: {q.get('score')}/100</b> — coverage {q.get('coverage')}%, "
                               f"consistency {q.get('consistency')}%, clarity {q.get('clarity')}%, linkage {q.get('linkage')}%", styles["Normal"]))
    items = _items(db, project.id)
    for type_, label in SECTIONS:
        group = [i for i in items if i.type == type_]
        if not group:
            continue
        story += [Spacer(1, 6), Paragraph(label, styles["Heading2"])]
        for i in group:
            story.append(Paragraph(f"<b>{i.key}</b> {escape(i.title)}", styles["Normal"]))
            for line in _detail_lines(i):
                story.append(Paragraph("&nbsp;&nbsp;• " + escape(str(line)), styles["Normal"]))
    rows = graph.trace_matrix(db, project.id)
    if rows:
        story += [Spacer(1, 6), Paragraph("Traceability Matrix", styles["Heading2"])]
        data = [["Req", "Stories", "APIs", "Tests", "Risks"]] + [
            [r["key"], ", ".join(r["storys"]), ", ".join(r["apis"]), ", ".join(r["tests"]), ", ".join(r["risks"])] for r in rows]
        t = Table(data, repeatRows=1, colWidths=[18 * mm, 35 * mm, 50 * mm, 40 * mm, 30 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
    pdf.build(story)
    return buf.getvalue()


EXPORTERS = {
    "json": (to_json, "application/json"),
    "csv": (to_csv, "text/csv"),
    "jira": (to_jira_csv, "text/csv"),
    "github": (to_github_issues, "application/json"),
    "docx": (to_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pdf": (to_pdf, "application/pdf"),
}
