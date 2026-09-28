"""End-to-end triage: request text in, validated TriageOutcome out.

Flow:
  1. Ask the LLM for a JSON triage (system prompt + rubric).
  2. Validate it against the schema; on failure, send the error back once
     and ask the model to fix its answer.
  3. If the provider is unavailable or the answer is still invalid, fall
     back to deterministic keyword rules, so the workflow never dead-ends.
  4. Apply safety guardrails to whichever result we got.
"""

import json
import re
import time

from pydantic import ValidationError

from .llm import LLMError, Provider, get_provider
from .prompts import MAX_REQUEST_CHARS, SYSTEM_PROMPT, build_repair_message, build_user_message
from .rules import apply_guardrails, rule_based_triage
from .schema import TriageOutcome, TriageResult

CHANNELS = ["Email", "Website form", "Chat"]
_AUTO = object()


def parse_json(raw: str) -> dict:
    """Extract the JSON object even if the model wrapped it in ``` fences or prose."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in the answer")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    return data


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}" for e in exc.errors()[:5]
        )
    return str(exc)


def _llm_triage(text: str, channel: str, provider: Provider) -> TriageResult:
    messages = [{"role": "user", "content": build_user_message(text, channel)}]
    error = ""
    for _ in range(2):  # first try + one repair attempt
        raw = provider.complete(SYSTEM_PROMPT, messages)
        try:
            return TriageResult.model_validate(parse_json(raw))
        except (ValueError, ValidationError) as exc:
            error = _short_error(exc)
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": build_repair_message(error)},
            ]
    raise ValueError(f"AI answer failed validation twice ({error})")


def triage(text: str, channel: str = "Email", provider=_AUTO) -> TriageOutcome:
    text = (text or "").strip()
    if not text:
        raise ValueError("Please enter a request to triage.")
    if provider is _AUTO:
        provider = get_provider()

    notes: list[str] = []
    if len(text) > MAX_REQUEST_CHARS:
        notes.append(f"Long request: only the first {MAX_REQUEST_CHARS} characters were analysed.")

    started = time.perf_counter()
    result, engine = None, "rules"
    if provider is not None:
        try:
            result = _llm_triage(text, channel, provider)
            engine = provider.label
        except (LLMError, ValueError) as exc:
            reason = str(exc).rstrip(".")
            notes.append(f"AI unavailable ({reason}). Used rule-based fallback - review carefully.")
    if result is None:
        result = rule_based_triage(text)
        if provider is None:
            notes.append("Rules-only mode (no AI key configured): labels come from keyword rules.")

    result, guard_notes = apply_guardrails(text, result)
    return TriageOutcome(
        result=result,
        engine=engine,
        review_notes=notes + guard_notes,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
