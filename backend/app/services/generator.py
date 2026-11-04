"""Blueprint generation: draft → schema validation → repair.

The LLM only drafts. Every draft must validate against ``BlueprintDraft``;
validation errors are fed back to the model for repair up to
``LLM_MAX_REPAIR_ATTEMPTS`` times, after which we fall back to the offline
heuristic generator so a project never ends up without a blueprint.
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from ..config import get_settings
from . import heuristic
from .blueprint_schema import BlueprintDraft, json_schema_text
from .llm import LLMError, get_provider, parse_json

log = logging.getLogger("specforge.generator")

SYSTEM_PROMPT = """You are SPECForge, a senior business analyst and software architect.
Convert the project brief into a complete, connected software blueprint.
Rules:
- Output ONE JSON object that validates against the JSON Schema provided. No prose.
- Keys: requirements REQ-001.., stories US-001.., modules MOD-001.., entities ENT-001..,
  apis API-001.., tests TC-001.., risks RSK-001.. (three digits).
- Every functional requirement (kind FR) has >=1 story, is covered by a module and has >=1 test.
- Every NFR has a test with a measurable expected result.
- Every API belongs to a module and lists the requirement_keys and entity_keys it serves.
- Only reference keys that exist in your output.
- Requirements must be atomic, testable and avoid vague words (fast, easy, user-friendly, etc.).
"""


class GenerationResult:
    def __init__(self, draft: BlueprintDraft, provider: str, attempts: int, fallback: bool, errors: list[str]):
        self.draft, self.provider, self.attempts, self.fallback, self.errors = draft, provider, attempts, fallback, errors


def generate_blueprint(brief: str) -> GenerationResult:
    provider = get_provider()
    if provider is None:
        return GenerationResult(BlueprintDraft.model_validate(heuristic.generate(brief)), "heuristic", 1, False, [])

    s = get_settings()
    user = f"JSON Schema:\n{json_schema_text()}\n\nProject brief:\n\"\"\"\n{brief[:60000]}\n\"\"\""
    errors: list[str] = []
    raw = ""
    for attempt in range(1, s.llm_max_repair_attempts + 2):
        try:
            if attempt == 1:
                raw = provider.complete_json(SYSTEM_PROMPT, user)
            else:
                raw = provider.complete_json(
                    SYSTEM_PROMPT,
                    f"{user}\n\nYour previous JSON was invalid:\n{errors[-1]}\n\nPrevious JSON:\n{raw[:30000]}\n\n"
                    "Return the corrected, complete JSON object.",
                )
            draft = BlueprintDraft.model_validate(parse_json(raw))
            return GenerationResult(draft, provider.name, attempt, False, errors)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc)[:4000])
            log.warning("draft attempt %s failed validation: %s", attempt, str(exc)[:300])
        except LLMError as exc:
            errors.append(str(exc))
            log.error("LLM provider error: %s", exc)
            break
    log.warning("falling back to heuristic generator after %s errors", len(errors))
    return GenerationResult(BlueprintDraft.model_validate(heuristic.generate(brief)), provider.name, len(errors), True, errors)


REPAIR_SYSTEM = """You repair gaps in a software blueprint. For each requirement listed, write the missing
items. Output JSON: {"stories": [...], "tests": [...]} where stories have
{requirement_key, role, goal, benefit, acceptance_criteria[]} and tests have
{requirement_key, title, type (functional|non_functional|negative), steps[], expected}."""


def repair_items(missing_story: list[dict], missing_test: list[dict]) -> tuple[list[dict], list[dict]]:
    """Generate story/test bodies for requirements that lack them.

    Returns (stories, tests) in heuristic-template shape but without keys.
    Uses the LLM when configured, otherwise deterministic templates.
    """
    provider = get_provider()
    if provider is not None and (missing_story or missing_test):
        try:
            payload = {
                "need_story": [{"requirement_key": r["key"], "text": r["description"]} for r in missing_story],
                "need_test": [{"requirement_key": r["key"], "kind": r["kind"], "text": r["description"]} for r in missing_test],
            }
            out = parse_json(provider.complete_json(REPAIR_SYSTEM, json.dumps(payload)))
            by_key = {r["key"]: r for r in missing_story + missing_test}
            stories = [
                {**heuristic.make_story("US-000", by_key[s["requirement_key"]]), **{k: s[k] for k in ("role", "goal", "benefit", "acceptance_criteria") if s.get(k)}}
                for s in out.get("stories", []) if s.get("requirement_key") in by_key
            ]
            tests = [
                {**heuristic.make_test("TC-000", by_key[t["requirement_key"]]), **{k: t[k] for k in ("title", "type", "steps", "expected") if t.get(k)}}
                for t in out.get("tests", []) if t.get("requirement_key") in by_key
            ]
            covered_s = {s["requirement_keys"][0] for s in stories}
            covered_t = {t["requirement_keys"][0] for t in tests}
            stories += [heuristic.make_story("US-000", r) for r in missing_story if r["key"] not in covered_s]
            tests += [heuristic.make_test("TC-000", r) for r in missing_test if r["key"] not in covered_t]
            return stories, tests
        except Exception as exc:  # noqa: BLE001 - never let repair crash the pipeline
            log.warning("LLM repair failed, using templates: %s", exc)
    return [heuristic.make_story("US-000", r) for r in missing_story], [heuristic.make_test("TC-000", r) for r in missing_test]
