import pytest
from pydantic import ValidationError

from app.services import heuristic, nlp
from app.services.blueprint_schema import BlueprintDraft


def test_schema_rejects_dangling_reference():
    bad = {"requirements": [{"key": "REQ-001", "title": "Login", "kind": "FR"}],
           "stories": [{"key": "US-001", "requirement_keys": ["REQ-999"], "role": "User", "goal": "log in"}]}
    with pytest.raises(ValidationError, match="unknown requirement REQ-999"):
        BlueprintDraft.model_validate(bad)


def test_schema_rejects_bad_key():
    with pytest.raises(ValidationError):
        BlueprintDraft.model_validate({"requirements": [{"key": "R1", "title": "Login", "kind": "FR"}]})


def test_heuristic_draft_is_valid(sample_brief):
    d = BlueprintDraft.model_validate(heuristic.generate(sample_brief))
    assert len(d.requirements) >= 10
    assert any(r.kind == "NFR" for r in d.requirements)
    assert d.constraints, "deadline/budget sentence should become a constraint"
    assert not any(r.title.startswith("#") for r in d.requirements)


@pytest.mark.parametrize("text,kind", [
    ("Users can upload a profile photo", "FR"),
    ("The page must load within 2 seconds", "NFR"),
    ("All data must be encrypted at rest", "NFR"),
])
def test_classifier(text, kind):
    assert nlp.classify_requirement(text)[0] == kind


def test_vague_terms():
    assert "user-friendly" in nlp.find_vague_terms("The UI must be user-friendly and fast")
    assert nlp.find_vague_terms("Response within 200 ms") == []


def test_contradiction_heuristic():
    assert nlp.contradiction_score("Users can delete their account", "Users cannot delete their account") >= 0.6
    assert nlp.contradiction_score("Session expires after 30 minutes", "Session expires after 60 minutes") >= 0.6
    assert nlp.contradiction_score("Users can upload photos", "Admins can export reports") < 0.6
