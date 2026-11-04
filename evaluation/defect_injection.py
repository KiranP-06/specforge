"""Defect-injection evaluation of the SPECForge consistency checker.

For every brief in evaluation/briefs/ the script
  1. generates a blueprint (with whatever LLM_PROVIDER is configured),
  2. records the Blueprint Quality Score *without* self-check repair (generator-only baseline),
  3. injects known defects into the graph — removed tests, removed stories, a paraphrased
     duplicate requirement, a contradicting requirement and a vague requirement,
  4. runs the checker and measures detection recall per defect type,
  5. runs the full self-check loop and reports the repaired score.

Usage (from repo root):
    PYTHONPATH=backend python evaluation/defect_injection.py [--seed 7] [--json results.json]
Set USE_TRANSFORMER_MODELS=true to evaluate the transformer ML layer instead of the lightweight one.
"""
import argparse
import json
import os
import pathlib
import random
import sys
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/eval.db")
os.environ.setdefault("INLINE_JOBS", "true")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Item, Link, Project, User  # noqa: E402
from app.services import checker, graph, nlp  # noqa: E402
from app.services.generator import generate_blueprint  # noqa: E402

PARAPHRASE = [("must be able to", "should be able to"), ("can ", "are able to "), ("shall", "must")]
NEGATE = [(" can ", " cannot "), (" must ", " must not "), (" should ", " should not "), (" shall ", " shall not ")]


def new_req(db, project, text):
    kind, cat = nlp.classify_requirement(text)
    it = Item(project_id=project.id, key=graph.next_key(db, project.id, "requirement"), type="requirement",
              title=text, description=text, data={"kind": kind, "category": cat, "priority": "should", "stakeholder": "User"},
              origin="manual", embedding=nlp.embed([text])[0])
    db.add(it)
    db.flush()
    return it


def evaluate(path: pathlib.Path, rng: random.Random, db, owner) -> dict:
    brief = path.read_text()
    res = generate_blueprint(brief)
    project = Project(name=path.stem, owner_id=owner.id, brief_text=brief)
    db.add(project)
    db.flush()
    graph.persist_draft(db, project, res.draft)
    base = checker.quality_score(db, project.id, checker.rule_checks(db, project.id) + checker.ml_checks(db, project.id))

    reqs = list(db.scalars(select(Item).where(Item.project_id == project.id, Item.type == "requirement")))
    frs = [r for r in reqs if r.data.get("kind") == "FR"]
    injected = {"missing_test": set(), "missing_story": set(), "duplicate": set(), "contradiction": set(), "vague_term": set()}

    for r in rng.sample(reqs, k=min(3, len(reqs))):  # remove all tests of 3 requirements
        db.execute(delete(Link).where(Link.source_id == r.id, Link.relation == "verified_by"))
        injected["missing_test"].add(r.id)
    for r in rng.sample(frs, k=min(2, len(frs))):    # remove stories of 2 FRs
        db.execute(delete(Link).where(Link.source_id == r.id, Link.relation == "refined_by"))
        injected["missing_story"].add(r.id)
    src = rng.choice(frs)
    text = src.description
    for a, b in PARAPHRASE:
        if a in text:
            text = text.replace(a, b, 1)
            break
    dup = new_req(db, project, text.rstrip(".") + " from the app.")
    injected["duplicate"].add(frozenset({src.id, dup.id}))
    src2 = rng.choice([r for r in frs if any(n.strip() in f" {r.description} " for n, _ in NEGATE)] or frs)
    neg = f" {src2.description} "
    for a, b in NEGATE:
        if a in neg:
            neg = neg.replace(a, b, 1)
            break
    con = new_req(db, project, neg.strip())
    injected["contradiction"].add(frozenset({src2.id, con.id}))
    vague = new_req(db, project, "The dashboard should be fast, intuitive and user-friendly.")
    injected["vague_term"].add(vague.id)
    db.flush()

    issues = checker.rule_checks(db, project.id) + checker.ml_checks(db, project.id)
    found = {
        "missing_test": {i.item_id for i in issues if i.kind == "missing_test"},
        "missing_story": {i.item_id for i in issues if i.kind == "missing_story"},
        "duplicate": {frozenset({i.item_id, i.related_item_id}) for i in issues if i.kind == "duplicate"},
        "contradiction": {frozenset({i.item_id, i.related_item_id}) for i in issues if i.kind == "contradiction"},
        "vague_term": {i.item_id for i in issues if i.kind == "vague_term"},
    }
    recall = {k: len(v & found[k]) / len(v) for k, v in injected.items() if v}
    injected_score = checker.quality_score(db, project.id, issues)["score"]
    repaired = checker.self_check(db, project)
    db.commit()
    return {"brief": path.stem, "provider": res.provider, "requirements": len(reqs), "generator_only_bqs": base["score"],
            "after_injection_bqs": injected_score, "after_self_check_bqs": repaired["score"],
            "auto_repaired": repaired["auto_repaired"], "recall": recall}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json")
    args = ap.parse_args()
    init_db()
    rng = random.Random(args.seed)
    db = SessionLocal()
    owner = User(email="eval@local", name="eval", password_hash="x", role="admin")
    db.add(owner)
    db.flush()
    rows = [evaluate(p, rng, db, owner) for p in sorted((pathlib.Path(__file__).parent / "briefs").glob("*.md"))]
    kinds = sorted({k for r in rows for k in r["recall"]})
    print(f"ML backend: {'transformers' if nlp.using_transformers() else 'lightweight'}\n")
    print(f"{'brief':<10}{'reqs':>5}{'BQS gen':>9}{'BQS inj':>9}{'BQS fixed':>11}{'repaired':>10}  " + "  ".join(f"{k[:13]:>13}" for k in kinds))
    for r in rows:
        print(f"{r['brief']:<10}{r['requirements']:>5}{r['generator_only_bqs']:>9}{r['after_injection_bqs']:>9}{r['after_self_check_bqs']:>11}{r['auto_repaired']:>10}  "
              + "  ".join(f"{r['recall'].get(k, float('nan')):>13.2f}" for k in kinds))
    mean = {k: sum(r["recall"].get(k, 0) for r in rows) / len(rows) for k in kinds}
    print("\nmean detection recall: " + ", ".join(f"{k}={v:.2f}" for k, v in mean.items()))
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps({"rows": rows, "mean_recall": mean}, indent=2))


if __name__ == "__main__":
    main()
