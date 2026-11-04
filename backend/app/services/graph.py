"""Blueprint graph: persistence of drafts as nodes/edges, traversal and change impact."""
from __future__ import annotations

import re
from collections import deque

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import Finding, Item, Link, Project
from . import nlp
from .blueprint_schema import BlueprintDraft

PREFIX = {
    "requirement": "REQ", "story": "US", "module": "MOD", "entity": "ENT", "api": "API", "test": "TC",
    "risk": "RSK", "stakeholder": "STK", "constraint": "CON",
}
TYPE_OF_PREFIX = {v: k for k, v in PREFIX.items()}
# Containment nodes are flagged by change impact but not expanded further,
# otherwise one edited requirement would flag every API of a large module.
NON_EXPANDING = {"module"}


def next_key(db: Session, project_id: int, type_: str) -> str:
    prefix = PREFIX[type_]
    keys = db.scalars(select(Item.key).where(Item.project_id == project_id, Item.type == type_)).all()
    nums = [int(m.group(1)) for k in keys if (m := re.match(rf"{prefix}-(\d+)$", k))]
    return f"{prefix}-{(max(nums) if nums else 0) + 1:03d}"


def add_link(db: Session, project_id: int, src: Item, dst: Item, relation: str) -> None:
    exists = db.scalar(select(Link.id).where(Link.source_id == src.id, Link.target_id == dst.id, Link.relation == relation))
    if not exists:
        db.add(Link(project_id=project_id, source_id=src.id, target_id=dst.id, relation=relation))


def clear_blueprint(db: Session, project_id: int) -> None:
    db.execute(delete(Finding).where(Finding.project_id == project_id))
    db.execute(delete(Link).where(Link.project_id == project_id))
    db.execute(delete(Item).where(Item.project_id == project_id))
    db.flush()


def item_text(it: Item) -> str:
    return f"{it.title}. {it.description}".strip()


def persist_draft(db: Session, project: Project, draft: BlueprintDraft) -> dict[str, Item]:
    """Write a validated draft into the relational graph. Returns key → Item."""
    pid = project.id
    by_key: dict[str, Item] = {}

    def node(type_: str, key: str, title: str, description: str = "", data: dict | None = None) -> Item:
        it = Item(project_id=pid, key=key, type=type_, title=title[:500], description=description, data=data or {})
        db.add(it)
        by_key[key] = it
        return it

    for i, s in enumerate(draft.stakeholders, 1):
        node("stakeholder", f"STK-{i:03d}", s.name, s.description)
    for i, c in enumerate(draft.constraints, 1):
        node("constraint", f"CON-{i:03d}", c[:200], c)
    for r in draft.requirements:
        node("requirement", r.key, r.title, r.description, {
            "kind": r.kind, "category": r.category, "priority": r.priority, "stakeholder": r.stakeholder,
            "source_quote": r.source_quote})
    for s in draft.stories:
        title = f"As a {s.role}, I want to {s.goal}" + (f" so that {s.benefit}" if s.benefit else "")
        node("story", s.key, title, "", {"role": s.role, "goal": s.goal, "benefit": s.benefit,
                                          "acceptance_criteria": s.acceptance_criteria, "priority": s.priority})
    for m in draft.modules:
        node("module", m.key, m.name, m.description)
    for e in draft.entities:
        node("entity", e.key, e.name, ", ".join(f.name for f in e.fields),
             {"fields": [f.model_dump() for f in e.fields]})
    for a in draft.apis:
        node("api", a.key, f"{a.method} {a.path}", a.summary, {"method": a.method, "path": a.path})
    for t in draft.tests:
        node("test", t.key, t.title, t.expected, {"type": t.type, "steps": t.steps, "expected": t.expected})
    for r in draft.risks:
        node("risk", r.key, r.title, r.description, {"likelihood": r.likelihood, "impact": r.impact,
                                                      "exposure": r.likelihood * r.impact, "mitigation": r.mitigation})
    db.flush()

    # embeddings for similarity search (pgvector in production)
    reqs = [by_key[r.key] for r in draft.requirements]
    for it, vec in zip(reqs, nlp.embed([item_text(x) for x in reqs]), strict=False):
        it.embedding = vec

    L = lambda a, b, rel: add_link(db, pid, by_key[a], by_key[b], rel)  # noqa: E731
    for s in draft.stories:
        for rk in s.requirement_keys:
            L(rk, s.key, "refined_by")
    for m in draft.modules:
        for rk in m.requirement_keys:
            L(rk, m.key, "allocated_to")
        for sk in m.story_keys:
            L(sk, m.key, "implemented_in")
    for e in draft.entities:
        if e.module_key:
            L(e.module_key, e.key, "owns")
    for a in draft.apis:
        if a.module_key:
            L(a.module_key, a.key, "exposes")
        for rk in a.requirement_keys:
            L(rk, a.key, "realised_by")
        for ek in a.entity_keys:
            L(a.key, ek, "uses")
    for t in draft.tests:
        for rk in t.requirement_keys:
            L(rk, t.key, "verified_by")
    for r in draft.risks:
        for rk in r.requirement_keys:
            L(rk, r.key, "threatened_by")
    db.flush()
    return by_key


def adjacency(db: Session, project_id: int) -> tuple[dict[int, list[tuple[int, str]]], dict[int, list[tuple[int, str]]]]:
    out: dict[int, list[tuple[int, str]]] = {}
    inc: dict[int, list[tuple[int, str]]] = {}
    for link in db.scalars(select(Link).where(Link.project_id == project_id)):
        out.setdefault(link.source_id, []).append((link.target_id, link.relation))
        inc.setdefault(link.target_id, []).append((link.source_id, link.relation))
    return out, inc


def downstream_impact(db: Session, item: Item) -> list[dict]:
    """Breadth-first traversal of every item that depends on ``item``."""
    out, _ = adjacency(db, item.project_id)
    seen = {item.id}
    q: deque[tuple[int, int, list[str]]] = deque([(item.id, 0, [item.key])])
    items = {i.id: i for i in db.scalars(select(Item).where(Item.project_id == item.project_id))}
    impacted: list[dict] = []
    while q:
        node_id, depth, path = q.popleft()
        node = items[node_id]
        if node_id != item.id and node.type in NON_EXPANDING:
            continue
        for nxt, rel in out.get(node_id, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            tgt = items[nxt]
            impacted.append({"id": tgt.id, "key": tgt.key, "type": tgt.type, "title": tgt.title,
                             "relation": rel, "depth": depth + 1, "path": path + [tgt.key]})
            q.append((nxt, depth + 1, path + [tgt.key]))
    return impacted


def propagate_change(db: Session, item: Item) -> list[dict]:
    impacted = downstream_impact(db, item)
    ids = [i["id"] for i in impacted]
    if ids:
        for it in db.scalars(select(Item).where(Item.id.in_(ids))):
            it.stale = True
            it.stale_reason = f"{item.key} changed (v{item.version}) — review this item"
    return impacted


def trace_matrix(db: Session, project_id: int) -> list[dict]:
    """One row per requirement with its linked stories, modules, APIs, entities, tests and risks."""
    items = {i.id: i for i in db.scalars(select(Item).where(Item.project_id == project_id))}
    out, inc = adjacency(db, project_id)
    rows = []
    for it in sorted((i for i in items.values() if i.type == "requirement"), key=lambda x: x.key):
        linked: dict[str, set[str]] = {t: set() for t in ("story", "module", "api", "entity", "test", "risk")}
        for nid, _ in out.get(it.id, []):
            n = items[nid]
            if n.type in linked:
                linked[n.type].add(n.key)
            if n.type == "api":
                for eid, _ in out.get(nid, []):
                    linked["entity"].add(items[eid].key)
            if n.type == "story":
                for mid, _ in out.get(nid, []):
                    if items[mid].type == "module":
                        linked["module"].add(items[mid].key)
        rows.append({"id": it.id, "key": it.key, "title": it.title, "kind": it.data.get("kind"),
                     "priority": it.data.get("priority"), "status": it.status, "stale": it.stale,
                     **{t + "s": sorted(v) for t, v in linked.items()}})
    return rows


def counts(db: Session, project_id: int) -> dict[str, int]:
    rows = db.execute(select(Item.type, func.count()).where(Item.project_id == project_id).group_by(Item.type)).all()
    return {t: n for t, n in rows}
