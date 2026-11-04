"""Pluggable LLM providers. Swap with LLM_PROVIDER without code changes."""
from __future__ import annotations

import json
import logging
import re
from typing import Protocol

import httpx

from ..config import get_settings

log = logging.getLogger("specforge.llm")


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> str: ...


class OpenAICompatibleProvider:
    """Works with OpenAI, Groq, OpenRouter, Together, Ollama (/v1) and Gemini's OpenAI endpoint."""

    name = "openai"

    def __init__(self):
        s = get_settings()
        self.base = s.llm_base_url.rstrip("/")
        self.key, self.model, self.timeout = s.llm_api_key, s.llm_model, s.llm_timeout_seconds

    def complete_json(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        try:
            r = httpx.post(f"{self.base}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise LLMError(f"OpenAI-compatible call failed: {exc}") from exc


class AnthropicProvider:
    name = "anthropic"

    def __init__(self):
        s = get_settings()
        self.key, self.model, self.timeout = s.llm_api_key, s.llm_model, s.llm_timeout_seconds
        self.base = s.llm_base_url.rstrip("/") if "anthropic" in s.llm_base_url else "https://api.anthropic.com/v1"

    def complete_json(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "max_tokens": 16000,
            "temperature": 0.2,
            "system": system + "\nRespond with a single JSON object only.",
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        try:
            r = httpx.post(f"{self.base}/messages", json=body, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"])
        except (httpx.HTTPError, KeyError) as exc:
            raise LLMError(f"Anthropic call failed: {exc}") from exc


def get_provider() -> LLMProvider | None:
    """Returns None for the offline heuristic provider."""
    name = get_settings().llm_provider.lower()
    if name in ("openai", "groq", "openrouter", "ollama", "gemini"):
        return OpenAICompatibleProvider()
    if name == "anthropic":
        return AnthropicProvider()
    return None


def parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in response")
    return json.loads(text[start : end + 1])
