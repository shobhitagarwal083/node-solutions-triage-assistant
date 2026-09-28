# Study guide: explain every part

The brief says: *"You must understand and be able to explain every important part of your solution."* Below are the questions a reviewer is likely to ask, with short answers.

## The 60-second explanation
A request goes into one LLM call. The system prompt holds the business rules: category definitions, a priority rubric, a routing table, reply-writing rules and a prompt-injection rule. The model must return JSON. Pydantic validates it against fixed enums. If validation fails, I send the error back once so the model can fix it. If the AI is unreachable or still wrong, keyword rules produce the result instead. Every result then passes through guardrails that enforce minimum priorities for data exposure and outages and flag risky drafts. Streamlit shows the result, and a human edits and sends the reply.

## Likely questions

**Why one LLM call and not an agent or several calls?**
The task is classification plus a short reply. One call is fast (a few seconds), cheap and easy to debug. Several calls would add latency and more places to fail without improving the labels.

**Why Gemini?**
The brief says don't spend money, and Gemini has a free tier that needs no card. The LLM layer is plain HTTPS, so switching to Groq, OpenRouter, a local Ollama model or a paid model is an `.env` change (`triage/llm.py`).

**How do you stop the model from inventing labels like "Critical"?**
The labels are Python enums (`triage/schema.py`). Pydantic rejects anything outside them. Small variations like `"urgent"` or `"sales team"` are normalised first, and anything else triggers the repair attempt.

**Why do the reasons come before the labels in the JSON?**
The model generates text in order. Asking it to write the justification first means the label follows from its reasoning, rather than being picked first and justified afterwards. It also gives the reviewer a visible "why".

**How did you decide priorities?**
By business impact, written as a rubric in the prompt:
- **Urgent:** outage, data or security exposure, legal risk
- **High:** a deadline within days or money at risk
- **Medium:** a real need with no immediate harm
- **Low:** ideas or no deadline

The prompt explicitly tells the model to ignore tone, so "URGENT!!!" on a logo change stays Low.

**Why is request 05 Technical/Engineering and not Support/Client Success?**
The immediate action is technical: revoke access to the workspace and file. Engineering can do that; Client Success can't. The guardrail also tells the reviewer to involve a security/privacy lead, because a data exposure may have compliance implications. Client Success is accepted in the eval as a reasonable alternative.

**Why is request 01 Medium and not High?**
It's a warm lead with clear pain, but nothing breaks if the reply comes tomorrow. "Next week" is a meeting preference, not a deadline. High is reserved for deadlines within days or money at risk. The eval accepts High as an alternative.

**Request 04: Engineering or Client Success?**
It's a product feature idea, so I route it to Engineering's backlog. Client Success (who gather client feedback) is equally defensible, and the eval accepts both. The main point is that it's Low.

**What are the guardrails and why have them if the LLM is good?**
LLMs are usually right, but a missed escalation for leaked data costs far more than a false alarm. So four deterministic checks run on every result:
- data-exposure keywords → at least Urgent
- outage keywords → at least High
- prompt-injection patterns → flagged
- amounts in the draft that aren't in the request → flagged

They can over-trigger. That's acceptable, because the reviewer sees the reason.

**How do you handle prompt injection?**
- The client text is wrapped in `<request>` tags and the prompt declares it to be data.
- Any `<request>`/`</request>` inside the text is escaped so it can't close the tag early.
- The model is told to triage the genuine content and flag `suspicious_content`.
- A regex guardrail flags common injection phrases too.

Edge case E6 tests this.

**What happens if the API is down or rate-limited?**
`llm.py` retries once on network or 5xx errors, and gives clear messages for 429 and 401. The pipeline catches the error and runs `rule_based_triage`. The UI shows "rule-based fallback" and a warning. The app also caches results to save free-tier quota.

**How did you test it?**
- **`eval.py`:** runs 15 cases (the 6 mocks + 9 synthetic edge cases) and scores category, priority and owner against acceptable answers, plus extra checks (required flags, invoice number extracted, no invented price).
- **`tests/`:** 10 unit tests with a fake LLM covering valid answers, fenced JSON, repair, fallback, guardrails, normalisation and empty input.

**Why aren't the six mocks in the prompt as examples?**
That would be teaching to the test. The few-shot examples are different, synthetic requests, so the eval measures real generalisation.

**What would you do with more time?**
Connect the real inbox and helpdesk, log reviewer corrections as training/eval data, add client context (tier, open incidents), SLA timers, split multi-issue tickets, and redact PII before the LLM call.

**Limitations?**
- It only sees the message text.
- One owner per request.
- Slight variation between LLM runs.
- The fallback is English-only.
- Sending text to a third-party LLM needs PII redaction in production.
- 15 test cases aren't enough to prove accuracy at scale.

## File-by-file
| File | One-line purpose |
|---|---|
| `triage/schema.py` | Allowed labels, result model, routing and response-time tables |
| `triage/prompts.py` | System prompt (the "brain"), user message wrapper, repair message |
| `triage/llm.py` | Calls Gemini or an OpenAI-compatible API; turns HTTP errors into readable messages |
| `triage/pipeline.py` | Orchestrates: LLM → validate → repair → fallback → guardrails |
| `triage/rules.py` | Keyword fallback classifier, template replies, guardrails |
| `app.py` | Streamlit UI: triage tab + inbox queue |
| `eval.py` + `data/cases.json` | Measures accuracy on mocks and edge cases |
| `tests/test_pipeline.py` | Unit tests with a fake LLM |
