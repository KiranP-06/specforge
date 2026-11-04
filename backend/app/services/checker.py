"""Consistency checker: rule layer + ML layer, auto-repair loop, Blueprint Quality Score."""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Finding, Item, Project
from . import graph, nlp
from .generator import repair_items

log = logging.getLogger("specforge.checker")
AUTO_FIXABLE = {"missing_story", "missing_test", "missing_module"}


@dataclass
class Issue:
    layer: str
    kind: str
    severity: str
    message: str
    item_id: int | None = None
    related_item_id: int | None = None
    score: float | None = None
    meta: dict = field(default_factory=dict)


def _load(db: Session, project_id: int):
    items = list(db.scalars(select(Item).where(Item.project_id == project_id)))
    out, inc = graph.adjacency(db, project_id)
    by_id = {i.id: i for i in items}
    return items, by_id, out, inc


def rule_checks(db: Session, project_id: int) -> list[Issue]:
    items, by_id, out, inc = _load(db, project_id)
    issues: list[Issue] = []

    def targets(i: Item, type_: str) -> list[Item]:
        return [by_id[t] for t, _ in out.get(i.id, []) if by_id[t].type == type_]

    def sources(i: Item, type_: str) -> list[Item]:
        return [by_id[s] for s, _ in inc.get(i.id, []) if by_id[s].type == type_]

    for r in (i for i in items if i.type == "requirement"):
        text = graph.item_text(r)
        kind = r.data.get("kind", "FR")
        if kind == "FR" and not targets(r, "story"):
            issues.append(Issue("rule", "missing_story", "error", f"{r.key} has no user story", r.id))
        if not targets(r, "test"):
            issues.append(Issue("rule", "missing_test", "error", f"{r.key} has no test scenario", r.id))
        if kind == "FR" and not targets(r, "module") and not any(targets(s, "module") for s in targets(r, "story")):
            issues.append(Issue("rule", "missing_module", "warning", f"{r.key} is not allocated to any module", r.id))
        vague = nlp.find_vague_terms(text)
        if vague:
            issues.append(Issue("rule", "vague_term", "warning",
                                f"{r.key} uses vague wording: {', '.join(vague)}", r.id, meta={"terms": vague}))
        if kind == "NFR" and not nlp.has_measurable_criterion(text):
            issues.append(Issue("rule", "unmeasurable_nfr", "warning",
                                f"{r.key} is non-functional but has no measurable threshold", r.id))
    for a in (i for i in items if i.type == "api"):
        if not sources(a, "requirement"):
            issues.append(Issue("rule", "orphan_api", "warning", f"{a.key} ({a.title}) serves no requirement", a.id))
        if not sources(a, "module"):
            issues.append(Issue("rule", "api_without_module", "info", f"{a.key} is not exposed by any module", a.id))
    for e in (i for i in items if i.type == "entity"):
        if not sources(e, "api"):
            issues.append(Issue("rule", "orphan_entity", "warning", f"{e.key} ({e.title}) is not used by any API", e.id))
    for s in (i for i in items if i.type == "story"):
        if not s.data.get("acceptance_criteria"):
            issues.append(Issue("rule", "missing_acceptance_criteria", "warning", f"{s.key} has no acceptance criteria", s.id))
        if not sources(s, "requirement"):
            issues.append(Issue("rule", "orphan_story", "warning", f"{s.key} is not linked to a requirement", s.id))
    for t in (i for i in items if i.type == "test"):
        if not sources(t, "requirement"):
            issues.append(Issue("rule", "orphan_test", "info", f"{t.key} does not verify any requirement", t.id))
    return issues


def ml_checks(db: Session, project_id: int) -> list[Issue]:
    reqs = list(db.scalars(select(Item).where(Item.project_id == project_id, Item.type == "requirement").order_by(Item.key)))
    issues: list[Issue] = []
    texts = [graph.item_text(r) for r in reqs]
    missing = [i for i, r in enumerate(reqs) if not r.embedding]
    if missing:
        for i, vec in zip(missing, nlp.embed([texts[i] for i in missing]), strict=False):
            reqs[i].embedding = vec
    thr = nlp.duplicate_threshold()
    for (i, a), (j, b) in itertools.combinations(enumerate(reqs), 2):
        sim = nlp.similarity(texts[i], texts[j], a.embedding, b.embedding)
        # Contradiction is checked first: a negated copy of a requirement is lexically
        # near-identical, so it would otherwise be mislabelled as a harmless duplicate.
        if sim >= 0.35 or nlp.jaccard(texts[i], texts[j]) >= 0.25:
            c = nlp.contradiction_score(texts[i], texts[j])
            if c >= 0.6:
                issues.append(Issue("ml", "contradiction", "error",
                                    f"{a.key} may contradict {b.key} (confidence {c:.2f})", a.id, b.id, round(c, 3)))
                continue
        if sim >= thr:
            issues.append(Issue("ml", "duplicate", "warning",
                                f"{a.key} and {b.key} look like duplicates (similarity {sim:.2f})", a.id, b.id, round(sim, 3)))
    # FR/NFR classifier disagreement with the generator's label
    for r, text in zip(reqs, texts, strict=False):
        kind, cat = nlp.classify_requirement(text)
        if r.data.get("kind") and kind != r.data.get("kind"):
            issues.append(Issue("ml", "classification_mismatch", "info",
                                f"{r.key} labelled {r.data.get('kind')} but classifier suggests {kind} ({cat})", r.id))
    return issues


def auto_repair(db: Session, project: Project, issues: list[Issue]) -> int:
    """Fix structural gaps automatically. Returns the number of items created/linked."""
    by_id = {i.id: i for i in db.scalars(select(Item).where(Item.project_id == project.id))}
    need_story = [by_id[i.item_id] for i in issues if i.kind == "missing_story"]
    need_test = [by_id[i.item_id] for i in issues if i.kind == "missing_test"]
    need_module = [by_id[i.item_id] for i in issues if i.kind == "missing_module"]
    as_dict = lambda r: {"key": r.key, "title": r.title, "description": r.description or r.title,  # noqa: E731
                         "kind": r.data.get("kind", "FR"), "category": r.data.get("category", "functional"),
                         "priority": r.data.get("priority", "should"), "stakeholder": r.data.get("stakeholder", "User")}
    stories, tests = repair_items([as_dict(r) for r in need_story], [as_dict(r) for r in need_test])
    fixed = 0
    req_by_key = {r.key: r for r in need_story + need_test}
    for s in stories:
        req = req_by_key[s["requirement_keys"][0]]
        title = f"As a {s['role']}, I want to {s['goal']}" + (f" so that {s['benefit']}" if s.get("benefit") else "")
        it = Item(project_id=project.id, key=graph.next_key(db, project.id, "story"), type="story", title=title[:500],
                  data={k: s[k] for k in ("role", "goal", "benefit", "acceptance_criteria", "priority")}, origin="repaired")
        db.add(it)
        db.flush()
        graph.add_link(db, project.id, req, it, "refined_by")
        fixed += 1
    for t in tests:
        req = req_by_key[t["requirement_keys"][0]]
        it = Item(project_id=project.id, key=graph.next_key(db, project.id, "test"), type="test", title=t["title"][:500],
                  description=t.get("expected", ""), data={k: t[k] for k in ("type", "steps", "expected")}, origin="repaired")
        db.add(it)
        db.flush()
        graph.add_link(db, project.id, req, it, "verified_by")
        fixed += 1
    if need_module:
        core = db.scalar(select(Item).where(Item.project_id == project.id, Item.type == "module", Item.title == "Core Workflow"))
        if core is None:
            core = Item(project_id=project.id, key=graph.next_key(db, project.id, "module"), type="module",
                        title="Core Workflow", description="Catch-all module created by the self-check.", origin="repaired")
            db.add(core)
            db.flush()
        for r in need_module:
            graph.add_link(db, project.id, r, core, "allocated_to")
            fixed += 1
    db.flush()
    return fixed


def quality_score(db: Session, project_id: int, issues: list[Issue]) -> dict:
    items = list(db.scalars(select(Item).where(Item.project_id == project_id)))
    reqs = [i for i in items if i.type == "requirement"]
    n = max(len(reqs), 1)
    kinds = {}
    for i in issues:
        kinds.setdefault(i.kind, set()).add(i.item_id)
    uncovered = len(kinds.get("missing_story", set()) | kinds.get("missing_test", set()) | kinds.get("missing_module", set()))
    coverage = 1 - uncovered / n
    dup = len(kinds.get("duplicate", set())) + len(kinds.get("contradiction", set())) * 2
    consistency = max(0.0, 1 - dup / n)
    unclear = len(kinds.get("vague_term", set()) | kinds.get("unmeasurable_nfr", set()))
    clarity = 1 - unclear / n
    linkable = [i for i in items if i.type in ("api", "entity", "story", "test")]
    orphans = sum(len(kinds.get(k, set())) for k in ("orphan_api", "orphan_entity", "orphan_story", "orphan_test"))
    linkage = 1 - orphans / max(len(linkable), 1)
    score = 100 * (0.40 * coverage + 0.25 * consistency + 0.20 * clarity + 0.15 * linkage)
    return {
        "score": round(score, 1),
        "coverage": round(coverage * 100, 1),
        "consistency": round(consistency * 100, 1),
        "clarity": round(clarity * 100, 1),
        "linkage": round(linkage * 100, 1),
        "weights": {"coverage": 0.40, "consistency": 0.25, "clarity": 0.20, "linkage": 0.15},
        "ml_backend": "transformers" if nlp.using_transformers() else "lightweight",
    }


def self_check(db: Session, project: Project, repair: bool = True) -> dict:
    """Run checks → auto-repair → re-check until clean or max iterations. Persists findings."""
    s = get_settings()
    iterations, repaired_total = 0, 0
    history = []
    while True:
        iterations += 1
        issues = rule_checks(db, project.id) + ml_checks(db, project.id)
        q = quality_score(db, project.id, issues)
        history.append({"iteration": iterations, "issues": len(issues), "score": q["score"]})
        fixable = [i for i in issues if i.kind in AUTO_FIXABLE]
        if not repair or not fixable or iterations >= s.max_self_check_iterations:
            break
        repaired_total += auto_repair(db, project, fixable)

    db.execute(delete(Finding).where(Finding.project_id == project.id))
    for i in issues:
        db.add(Finding(project_id=project.id, item_id=i.item_id, related_item_id=i.related_item_id, layer=i.layer,
                       kind=i.kind, severity=i.severity, message=i.message, score=i.score))
    project.quality_score = q["score"]
    project.quality_breakdown = {**q, "iterations": history, "auto_repaired": repaired_total}
    db.flush()
    return project.quality_breakdown
