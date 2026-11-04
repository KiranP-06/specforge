from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Comment, Item, ItemVersion, Link, Project, User
from ..schemas import (
    ChangeResult,
    CommentIn,
    CommentOut,
    ItemIn,
    ItemOut,
    ItemPatch,
    LinkIn,
    LinkOut,
    ReviewIn,
    VersionOut,
)
from ..security import get_current_user, require_roles
from ..services import graph, nlp

router = APIRouter(prefix="/api", tags=["blueprint"])
CONTENT_FIELDS = ("title", "description", "data")


def get_item(item_id: int, db: Session) -> Item:
    it = db.get(Item, item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    return it


def snapshot(it: Item) -> dict:
    return {"key": it.key, "title": it.title, "description": it.description, "data": it.data, "status": it.status,
            "review_state": it.review_state}


@router.get("/projects/{project_id}/items", response_model=list[ItemOut])
def list_items(project_id: int, type: str | None = None, stale: bool | None = None, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    q = select(Item).where(Item.project_id == project_id)
    if type:
        q = q.where(Item.type == type)
    if stale is not None:
        q = q.where(Item.stale == stale)
    return db.scalars(q.order_by(Item.type, Item.key)).all()


@router.post("/projects/{project_id}/items", response_model=ItemOut, status_code=201)
def create_item(project_id: int, body: ItemIn, db: Session = Depends(get_db), user: User = Depends(require_roles("analyst"))):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    it = Item(project_id=project_id, key=graph.next_key(db, project_id, body.type), type=body.type, title=body.title,
              description=body.description, data=body.data, origin="manual")
    if body.type == "requirement":
        kind, cat = nlp.classify_requirement(f"{body.title}. {body.description}")
        it.data = {"kind": kind, "category": cat, "priority": "should", "stakeholder": "User", **body.data}
        it.embedding = nlp.embed([graph.item_text(it)])[0]
    db.add(it)
    db.flush()
    for src_id in body.link_from:
        src = get_item(src_id, db)
        graph.add_link(db, project_id, src, it, _default_relation(src.type, it.type))
    db.add(ItemVersion(item_id=it.id, version=1, snapshot=snapshot(it), changed_by=user.id, change_note="created"))
    db.commit()
    return it


def _default_relation(src: str, dst: str) -> str:
    return {("requirement", "story"): "refined_by", ("requirement", "test"): "verified_by",
            ("requirement", "risk"): "threatened_by", ("requirement", "api"): "realised_by",
            ("requirement", "module"): "allocated_to", ("module", "api"): "exposes", ("module", "entity"): "owns",
            ("api", "entity"): "uses", ("story", "module"): "implemented_in"}.get((src, dst), "relates_to")


@router.get("/items/{item_id}", response_model=ItemOut)
def read_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return get_item(item_id, db)


@router.get("/items/{item_id}/links")
def item_links(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    it = get_item(item_id, db)
    out = db.execute(select(Link, Item).join(Item, Item.id == Link.target_id).where(Link.source_id == it.id)).all()
    inc = db.execute(select(Link, Item).join(Item, Item.id == Link.source_id).where(Link.target_id == it.id)).all()
    fmt = lambda l, i: {"link_id": l.id, "relation": l.relation, "id": i.id, "key": i.key, "type": i.type, "title": i.title}  # noqa: E731
    return {"downstream": [fmt(l, i) for l, i in out], "upstream": [fmt(l, i) for l, i in inc]}


@router.patch("/items/{item_id}", response_model=ChangeResult)
def update_item(item_id: int, body: ItemPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Edit an item. Content edits bump the version and flag every dependent item (change impact).

    Analysts/admins may edit content; any role may update delivery status.
    """
    it = get_item(item_id, db)
    changes = body.model_dump(exclude_none=True, exclude={"change_note"})
    content_change = any(k in CONTENT_FIELDS and changes[k] != getattr(it, k) for k in changes)
    if content_change and user.role not in ("admin", "analyst"):
        raise HTTPException(403, "Only analysts can change blueprint content")
    for k, v in changes.items():
        setattr(it, k, v)
    impacted: list[dict] = []
    if content_change:
        it.version += 1
        it.review_state = "draft"
        it.stale, it.stale_reason = False, None
        if it.type == "requirement":
            it.embedding = nlp.embed([graph.item_text(it)])[0]
        db.add(ItemVersion(item_id=it.id, version=it.version, snapshot=snapshot(it), changed_by=user.id,
                           change_note=body.change_note or "edited"))
        db.flush()
        impacted = graph.propagate_change(db, it)
    db.commit()
    db.refresh(it)
    return ChangeResult(item=ItemOut.model_validate(it), impacted=impacted)


@router.get("/items/{item_id}/impact")
def preview_impact(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Dry run: which items would be flagged if this item changed."""
    return graph.downstream_impact(db, get_item(item_id, db))


@router.post("/items/{item_id}/acknowledge", response_model=ItemOut)
def acknowledge(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Mark a stale (impacted) item as reviewed and still valid."""
    it = get_item(item_id, db)
    it.stale, it.stale_reason = False, None
    db.commit()
    return it


@router.post("/items/{item_id}/review", response_model=ItemOut)
def review(item_id: int, body: ReviewIn, db: Session = Depends(get_db), user: User = Depends(require_roles("reviewer"))):
    it = get_item(item_id, db)
    it.review_state = body.state
    if body.comment:
        db.add(Comment(item_id=it.id, author_id=user.id, body=f"[{body.state}] {body.comment}"))
    db.commit()
    return it


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("analyst"))):
    it = get_item(item_id, db)
    graph.propagate_change(db, it)  # dependents are flagged stale before their upstream disappears
    db.delete(it)
    db.commit()


@router.get("/items/{item_id}/versions", response_model=list[VersionOut])
def versions(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(ItemVersion).where(ItemVersion.item_id == item_id).order_by(ItemVersion.version.desc())).all()


@router.get("/items/{item_id}/comments", response_model=list[CommentOut])
def comments(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(Comment).where(Comment.item_id == item_id).order_by(Comment.id)).all()


@router.post("/items/{item_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(item_id: int, body: CommentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_item(item_id, db)
    c = Comment(item_id=item_id, author_id=user.id, body=body.body)
    db.add(c)
    db.commit()
    return c


@router.post("/projects/{project_id}/links", response_model=LinkOut, status_code=201)
def create_link(project_id: int, body: LinkIn, db: Session = Depends(get_db), _: User = Depends(require_roles("analyst"))):
    src, dst = get_item(body.source_id, db), get_item(body.target_id, db)
    if src.project_id != project_id or dst.project_id != project_id or src.id == dst.id:
        raise HTTPException(400, "Both items must belong to this project and differ")
    link = Link(project_id=project_id, source_id=src.id, target_id=dst.id, relation=body.relation)
    db.add(link)
    db.commit()
    return link


@router.delete("/links/{link_id}", status_code=204)
def delete_link(link_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("analyst"))):
    link = db.get(Link, link_id)
    if not link:
        raise HTTPException(404, "Link not found")
    db.delete(link)
    db.commit()
