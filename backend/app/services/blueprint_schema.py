"""The schema every generated blueprint draft must satisfy.

The LLM (or the offline heuristic generator) must emit JSON matching
``BlueprintDraft``. Anything that fails validation is sent back for repair.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Priority = Literal["must", "should", "could", "wont"]
KEY_RE = re.compile(r"^[A-Z]{2,5}-\d{3}$")


class _Keyed(BaseModel):
    key: str

    @field_validator("key")
    @classmethod
    def _key_format(cls, v: str) -> str:
        if not KEY_RE.match(v):
            raise ValueError(f"key '{v}' must look like REQ-001")
        return v


class Stakeholder(BaseModel):
    name: str
    description: str = ""


class Requirement(_Keyed):
    title: str = Field(min_length=3)
    description: str = ""
    kind: Literal["FR", "NFR"]
    category: str = "functional"
    priority: Priority = "should"
    stakeholder: str = "User"
    source_quote: str = ""


class Story(_Keyed):
    requirement_keys: list[str] = Field(min_length=1)
    role: str
    goal: str
    benefit: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: Priority = "should"


class Module(_Keyed):
    name: str
    description: str = ""
    requirement_keys: list[str] = Field(default_factory=list)
    story_keys: list[str] = Field(default_factory=list)


class EntityField(BaseModel):
    name: str
    type: str = "string"


class Entity(_Keyed):
    name: str
    fields: list[EntityField] = Field(default_factory=list)
    module_key: str | None = None


class Api(_Keyed):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    summary: str
    module_key: str | None = None
    entity_keys: list[str] = Field(default_factory=list)
    requirement_keys: list[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("path must start with '/'")
        return v


class TestCase(_Keyed):
    title: str
    requirement_keys: list[str] = Field(min_length=1)
    type: Literal["functional", "non_functional", "negative"] = "functional"
    steps: list[str] = Field(default_factory=list)
    expected: str = ""


class Risk(_Keyed):
    title: str
    description: str = ""
    likelihood: int = Field(ge=1, le=5, default=3)
    impact: int = Field(ge=1, le=5, default=3)
    mitigation: str = ""
    requirement_keys: list[str] = Field(default_factory=list)


class BlueprintDraft(BaseModel):
    summary: str = ""
    stakeholders: list[Stakeholder] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(min_length=1)
    stories: list[Story] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    apis: list[Api] = Field(default_factory=list)
    tests: list[TestCase] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_resolve(self) -> "BlueprintDraft":
        """Every cross-reference must point at a key that exists in the draft."""
        req = {r.key for r in self.requirements}
        stories = {s.key for s in self.stories}
        mods = {m.key for m in self.modules}
        ents = {e.key for e in self.entities}
        all_keys = [x.key for coll in (self.requirements, self.stories, self.modules, self.entities,
                                       self.apis, self.tests, self.risks) for x in coll]
        dupes = {k for k in all_keys if all_keys.count(k) > 1}
        errors: list[str] = []
        if dupes:
            errors.append(f"duplicate keys: {sorted(dupes)}")

        def check(owner: str, refs: list[str], valid: set[str], label: str):
            for ref in refs:
                if ref not in valid:
                    errors.append(f"{owner} references unknown {label} {ref}")

        for s in self.stories:
            check(s.key, s.requirement_keys, req, "requirement")
        for m in self.modules:
            check(m.key, m.requirement_keys, req, "requirement")
            check(m.key, m.story_keys, stories, "story")
        for e in self.entities:
            if e.module_key:
                check(e.key, [e.module_key], mods, "module")
        for a in self.apis:
            if a.module_key:
                check(a.key, [a.module_key], mods, "module")
            check(a.key, a.entity_keys, ents, "entity")
            check(a.key, a.requirement_keys, req, "requirement")
        for t in self.tests:
            check(t.key, t.requirement_keys, req, "requirement")
        for r in self.risks:
            check(r.key, r.requirement_keys, req, "requirement")
        if errors:
            raise ValueError("; ".join(errors[:20]))
        return self


def json_schema_text() -> str:
    import json

    return json.dumps(BlueprintDraft.model_json_schema(), indent=None)
