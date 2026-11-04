"""Request/response models for the REST API."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

ItemType = Literal["requirement", "story", "module", "entity", "api", "test", "risk", "stakeholder", "constraint"]
Status = Literal["todo", "in_progress", "done", "blocked"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class RoleIn(BaseModel):
    role: Literal["admin", "analyst", "reviewer"]


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    brief_text: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    brief_text: str | None = None


class ProjectOut(ORM):
    id: int
    name: str
    description: str
    owner_id: int
    brief_text: str
    brief_filename: str | None
    status: str
    quality_score: float | None
    quality_breakdown: dict | None
    baseline_version: int
    created_at: datetime
    updated_at: datetime


class ProjectSummary(ORM):
    id: int
    name: str
    description: str
    status: str
    quality_score: float | None
    baseline_version: int
    updated_at: datetime


class JobOut(ORM):
    id: int
    project_id: int
    kind: str
    status: str
    stage: str
    progress: int
    error: str | None
    result: dict | None
    created_at: datetime


class ItemOut(ORM):
    id: int
    project_id: int
    key: str
    type: str
    title: str
    description: str
    data: dict
    status: str
    review_state: str
    stale: bool
    stale_reason: str | None
    origin: str
    version: int
    updated_at: datetime


class ItemIn(BaseModel):
    type: ItemType
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    data: dict = Field(default_factory=dict)
    link_from: list[int] = Field(default_factory=list, description="upstream item ids")


class ItemPatch(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    data: dict | None = None
    status: Status | None = None
    change_note: str = ""


class ReviewIn(BaseModel):
    state: Literal["approved", "rejected", "draft"]
    comment: str = ""


class LinkIn(BaseModel):
    source_id: int
    target_id: int
    relation: str = Field(min_length=2, max_length=30)


class LinkOut(ORM):
    id: int
    source_id: int
    target_id: int
    relation: str


class FindingOut(ORM):
    id: int
    item_id: int | None
    related_item_id: int | None
    layer: str
    kind: str
    severity: str
    message: str
    score: float | None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentOut(ORM):
    id: int
    item_id: int
    author_id: int
    body: str
    created_at: datetime


class VersionOut(ORM):
    id: int
    version: int
    snapshot: dict
    changed_by: int | None
    change_note: str
    created_at: datetime


class BaselineIn(BaseModel):
    note: str = ""


class BaselineOut(ORM):
    id: int
    version: int
    quality_score: float | None
    approved_by: int
    note: str
    created_at: datetime


class ChangeResult(BaseModel):
    item: ItemOut
    impacted: list[dict]
