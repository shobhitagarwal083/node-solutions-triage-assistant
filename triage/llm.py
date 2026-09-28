"""Thin, swappable LLM layer.

Two providers, both called over plain HTTPS so there is no SDK lock-in:
- gemini: Google Gemini API (free tier, no credit card) - the default.
- openai_compatible: any OpenAI-style /chat/completions endpoint
  (Groq free tier, OpenRouter, a local Ollama server, OpenAI, ...).

Messages are a list of {"role": "user" | "assistant", "content": str}.
"""

import os
import time
from dataclasses import dataclass

import requests

TIMEOUT_S = 45


class LLMError(Exception):
    """Raised with a human-readable message when the provider call fails."""


@dataclass
class Provider:
    name: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"

    def complete(self, system: str, messages: list[dict]) -> str:  # pragma: no cover
        raise NotImplementedError


def _post(url: str, headers: dict, body: dict) -> dict:
    """POST with one retry on transient errors, and friendly error messages."""
    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=TIMEOUT_S)
        except requests.RequestException as exc:
            if attempt == 0:
                time.sleep(1.5)
                continue
            raise LLMError(f"Could not reach the AI provider ({exc.__class__.__name__}).") from exc

        if resp.status_code in (500, 502, 503, 504) and attempt == 0:
            time.sleep(1.5)
            continue
        if resp.status_code == 429:
            raise LLMError("AI provider rate limit reached (free tier). Try again in a minute.")
        if resp.status_code in (401, 403):
            raise LLMError("AI provider rejected the API key. Check your .env / secrets.")
        if resp.status_code == 404:
            raise LLMError("AI model not found. Check the model name in your .env / secrets.")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except ValueError:
                detail = resp.text[:200]
            raise LLMError(f"AI provider error {resp.status_code}: {detail}")
        return resp.json()
    raise LLMError("AI provider unavailable.")


class GeminiProvider(Provider):
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str):
        super().__init__(name="gemini", model=model)
        self._key = api_key

    def complete(self, system: str, messages: list[dict]) -> str:
        contents = [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in messages
        ]
        # Generous limit: on thinking models, reasoning tokens count toward it too.
        config = {"responseMimeType": "application/json", "maxOutputTokens": 8192}
        if self.model.startswith("gemini-3"):
            # Gemini 3 docs advise keeping the default temperature; low thinking keeps it fast.
            config["thinkingConfig"] = {"thinkingLevel": "low"}
        else:
            config["temperature"] = 0
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": config,
        }
        url = self.URL.format(model=self.model)
        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json"}
        try:
            data = _post(url, headers, body)
        except LLMError as exc:
            # Older/other models may not accept thinkingConfig: retry once without it.
            if "thinking" not in str(exc).lower() or "thinkingConfig" not in config:
                raise
            config.pop("thinkingConfig")
            data = _post(url, headers, body)
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no content returned")
            raise LLMError(f"Gemini returned no answer ({reason}).")
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise LLMError("Gemini returned an empty answer.")
        return text


class OpenAICompatibleProvider(Provider):
    def __init__(self, api_key: str, model: str, base_url: str):
        super().__init__(name="openai_compatible", model=model)
        self._key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"

    def complete(self, system: str, messages: list[dict]) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        data = _post(self._url, headers, body)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("AI provider returned an unexpected response shape.")


def get_provider() -> Provider | None:
    """Pick a provider from environment variables; None means rules-only mode.

    TRIAGE_PROVIDER = auto (default) | gemini | openai_compatible | rules
    """
    choice = os.getenv("TRIAGE_PROVIDER", "auto").strip().lower()
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    llm_base = os.getenv("LLM_BASE_URL")

    if choice == "rules":
        return None
    if choice in ("auto", "gemini") and gemini_key:
        return GeminiProvider(gemini_key, os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    if choice in ("auto", "openai_compatible") and llm_base:
        return OpenAICompatibleProvider(
            os.getenv("LLM_API_KEY", ""),
            os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            llm_base,
        )
    return None
