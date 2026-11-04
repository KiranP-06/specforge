# ADR 0002: Pluggable LLM provider with a deterministic offline generator

**Status:** accepted

## Context
The project has no GPU and no paid API budget, and the panel must be able to see a working demo even if an API quota runs out. LLM output is also non-deterministic and can be malformed.

## Decision
- All generation goes through one schema, `BlueprintDraft` (Pydantic). Any provider's output must validate. Validation errors are fed back to the model for repair, up to `LLM_MAX_REPAIR_ATTEMPTS` times.
- Providers sit behind a small interface: the OpenAI-compatible provider (which covers OpenAI, Groq, OpenRouter, Gemini and Ollama) and Anthropic, selected with `LLM_PROVIDER`.
- A rule-based **heuristic generator** is the default, the fallback, and the template source for repair stubs.

## Consequences
- The system always produces a blueprint, and CI tests are deterministic.
- The heuristic generator's quality is lower than an LLM's on free-form briefs. The self-checking layer is what guarantees structural completeness in both modes.
- The novelty does not depend on any particular model: the LLM is one replaceable part.
