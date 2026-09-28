"""Streamlit UI for the AI Request Triage Assistant.

Run locally:  streamlit run app.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
try:  # On Streamlit Cloud, keys live in st.secrets; expose them as env vars.
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

from triage import CHANNELS, TriageOutcome, triage  # noqa: E402
from triage.llm import get_provider  # noqa: E402
from triage.schema import Flag, Priority  # noqa: E402

st.set_page_config(page_title="Request Triage Assistant", page_icon="📥", layout="wide")

PRIORITY_COLOR = {"Urgent": "#C62828", "High": "#E65100", "Medium": "#1565C0", "Low": "#2E7D32"}
PRIORITY_ICON = {"Urgent": "🔴", "High": "🟠", "Medium": "🔵", "Low": "🟢"}
CATEGORY_COLOR = "#37474F"
OWNER_COLOR = "#4527A0"

CASES = json.loads((Path(__file__).parent / "data" / "cases.json").read_text())["cases"]
MOCKS = [c for c in CASES if c["set"] == "mock"]
WRITE_OWN = "✍️  Write my own request"
SAMPLES = {
    f"{'Mock' if c['set'] == 'mock' else 'Edge case'} {c['id']} · {c['title']}": c for c in CASES
}

st.markdown(
    """
    <style>
      .tri-label {font-size:0.72rem; letter-spacing:0.08em; text-transform:uppercase;
                  opacity:0.65; margin-bottom:6px;}
      .tri-badge {display:inline-block; color:#fff; padding:5px 14px; border-radius:999px;
                  font-weight:600; font-size:0.95rem;}
      .tri-box {border:1px solid rgba(128,128,128,0.25); border-radius:12px; padding:12px 14px;
                margin-bottom:10px;}
      .tri-chip {display:inline-block; background:rgba(128,128,128,0.14); border-radius:6px;
                 padding:2px 9px; margin:0 6px 6px 0; font-size:0.85rem;}
      .tri-flag {display:inline-block; border:1px solid rgba(198,40,40,0.5); color:inherit;
                 border-radius:6px; padding:1px 8px; margin:0 6px 6px 0; font-size:0.8rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------ state + engine
@st.cache_resource
def _shared_cache() -> dict:
    """Results shared across sessions, to save free-tier API quota on repeat demos."""
    return {}


def run_triage(text: str, channel: str) -> TriageOutcome:
    provider = get_provider()
    sig = provider.label if provider else "rules"
    key = (text.strip(), channel, sig)
    cache = _shared_cache()
    if key in cache:
        return TriageOutcome.model_validate(cache[key])
    outcome = triage(text, channel, provider=provider)
    # Don't cache a fallback result when AI is configured - retry AI next time.
    if provider is None or outcome.engine != "rules":
        cache[key] = outcome.model_dump(mode="json")
    return outcome


def add_to_queue(text: str, channel: str, outcome: TriageOutcome) -> None:
    queue = [q for q in st.session_state.queue if (q["text"], q["channel"]) != (text, channel)]
    queue.append({"text": text, "channel": channel, "outcome": outcome, "at": datetime.now()})
    st.session_state.queue = queue


st.session_state.setdefault("queue", [])
st.session_state.setdefault("current", None)
st.session_state.setdefault("request_text", "")
st.session_state.setdefault("channel", "Email")


def _load_sample():
    case = SAMPLES.get(st.session_state.sample_choice)
    st.session_state.request_text = case["text"] if case else ""
    if case:
        st.session_state.channel = case["channel"]
    st.session_state.current = None


def _clear():
    st.session_state.request_text = ""
    st.session_state.sample_choice = WRITE_OWN
    st.session_state.current = None


# ------------------------------------------------------------------ rendering
def badge(label: str, value: str, color: str) -> str:
    return (
        f'<div class="tri-box"><div class="tri-label">{label}</div>'
        f'<span class="tri-badge" style="background:{color}">{value}</span></div>'
    )


def render_outcome(outcome: TriageOutcome, key: str) -> None:
    r = outcome.result
    c1, c2, c3 = st.columns(3)
    c1.markdown(badge("Category", r.category.value, CATEGORY_COLOR), unsafe_allow_html=True)
    c2.markdown(
        badge("Priority", r.priority.value, PRIORITY_COLOR[r.priority.value]),
        unsafe_allow_html=True,
    )
    c3.markdown(badge("Route to", r.owner.value, OWNER_COLOR), unsafe_allow_html=True)
    st.markdown(f"⏱️ **Target first response:** {outcome.response_target}")

    if outcome.review_notes:
        notes = "\n".join(f"- {n}" for n in outcome.review_notes)
        box = st.error if Flag.DATA_EXPOSURE in r.flags else st.warning
        box(f"**Check before sending**\n\n{notes}", icon="⚠️")

    st.markdown("##### Summary")
    st.write(r.summary)
    if r.key_details:
        st.markdown(
            "".join(f'<span class="tri-chip">{d}</span>' for d in r.key_details),
            unsafe_allow_html=True,
        )

    st.markdown("##### Why these labels")
    st.markdown(
        f"- **Category - {r.category.value}:** {r.category_reason or '—'}\n"
        f"- **Priority - {r.priority.value}:** {r.priority_reason}\n"
        f"- **Owner - {r.owner.value}:** {r.routing_reason or '—'}"
    )
    if r.flags:
        st.markdown(
            "".join(f'<span class="tri-flag">{f.value.replace("_", " ")}</span>' for f in r.flags),
            unsafe_allow_html=True,
        )

    st.markdown("##### Draft first response")
    draft = st.text_area(
        "Review and edit before sending",
        value=r.draft_response,
        height=280,
        key=f"draft_{key}",
    )
    with st.expander("📋 Copy-ready version"):
        st.code(draft, language=None, wrap_lines=True)

    engine = "rule-based fallback" if outcome.engine == "rules" else outcome.engine
    st.caption(
        f"Engine: {engine} · confidence {r.confidence:.0%} · {outcome.latency_ms} ms · "
        "Auto-generated - a team member must review before sending."
    )
    st.download_button(
        "Download triage as JSON",
        data=outcome.model_dump_json(indent=2),
        file_name="triage.json",
        mime="application/json",
        key=f"dl_{key}",
    )


# ------------------------------------------------------------------ sidebar
provider = get_provider()
with st.sidebar:
    st.markdown("### Engine")
    if provider:
        st.success(f"AI connected: `{provider.model}`", icon="✅")
    else:
        st.warning(
            "Rules-only mode. Add `GEMINI_API_KEY` to `.env` (free at aistudio.google.com) "
            "to enable AI.",
            icon="⚙️",
        )
    st.markdown("### How it works")
    st.markdown(
        "1. The LLM reads the request against a written rubric and returns strict JSON.\n"
        "2. The JSON is validated; invalid answers get one repair attempt.\n"
        "3. If the AI is unavailable, keyword rules take over.\n"
        "4. Safety guardrails check every result (data exposure, outages, prompt injection, "
        "invented prices).\n"
        "5. A human reviews and sends the draft."
    )
    with st.expander("Priority rubric"):
        st.markdown(
            "- 🔴 **Urgent** - outage blocking work, data/security exposure, legal risk · 1 hour\n"
            "- 🟠 **High** - deadline in days, money at risk · same business day\n"
            "- 🔵 **Medium** - real need, no immediate harm · 1 business day\n"
            "- 🟢 **Low** - ideas, feedback, no deadline · 3 business days"
        )
    with st.expander("Routing"):
        st.markdown(
            "- Sales → **Sales Team**\n- Support → **Client Success**\n- Billing → **Finance**\n"
            "- Technical → **Engineering**\n- Other → **Client Success**"
        )

# ------------------------------------------------------------------ main
st.title("📥 Request Triage Assistant")
st.caption(
    "Paste a client email, web-form submission or chat message. Get a summary, category, "
    "priority, owner and a draft reply in seconds. A person always reviews before sending."
)

tab_triage, tab_queue = st.tabs(["Triage a request", "Inbox queue"])

with tab_triage:
    left, right = st.columns([5, 7], gap="large")
    with left:
        st.selectbox(
            "Start from a sample (optional)",
            [WRITE_OWN, *SAMPLES.keys()],
            key="sample_choice",
            on_change=_load_sample,
        )
        st.text_area(
            "Client request",
            key="request_text",
            height=220,
            placeholder="Paste the client's message here…",
        )
        st.radio("Received via", CHANNELS, key="channel", horizontal=True)
        b1, b2 = st.columns([3, 1])
        go = b1.button("Triage request", type="primary", width="stretch")
        b2.button("Clear", on_click=_clear, width="stretch")

        if go:
            text = st.session_state.request_text
            if not text.strip():
                st.error("Please paste or type a request first.")
            else:
                with st.spinner("Reading the request…"):
                    outcome = run_triage(text, st.session_state.channel)
                st.session_state.current = (text, st.session_state.channel, outcome)
                add_to_queue(text, st.session_state.channel, outcome)

    with right:
        if st.session_state.current:
            text, channel, outcome = st.session_state.current
            render_outcome(outcome, key=f"main_{abs(hash((text, channel)))}")
        else:
            st.info("Pick a sample or paste a request, then press **Triage request**.", icon="👈")

with tab_queue:
    queue = st.session_state.queue
    top_l, top_r = st.columns([3, 2])
    top_l.markdown(
        "Every request triaged in this session, **most urgent first**, with its owner. "
        "This is the view a team lead would use to make sure nothing important waits."
    )
    if top_r.button(f"Triage all {len(MOCKS)} mock requests", type="primary", width="stretch"):
        bar = st.progress(0.0, text="Triaging mock requests…")
        for i, case in enumerate(MOCKS, start=1):
            outcome = run_triage(case["text"], case["channel"])
            add_to_queue(case["text"], case["channel"], outcome)
            bar.progress(i / len(MOCKS), text=f"Triaged {i}/{len(MOCKS)}")
        bar.empty()
        queue = st.session_state.queue

    if not queue:
        st.info("The queue is empty. Triage a request, or triage all mock requests above.")
    else:
        ordered = sorted(
            queue, key=lambda q: (-q["outcome"].result.priority.rank, q["at"])
        )
        counts = {p.value: 0 for p in reversed(Priority)}
        for q in queue:
            counts[q["outcome"].result.priority.value] += 1
        for col, (p, n) in zip(st.columns(4), counts.items()):
            col.metric(f"{PRIORITY_ICON[p]} {p}", n)

        rows = [
            {
                "Priority": f"{PRIORITY_ICON[q['outcome'].result.priority.value]} "
                f"{q['outcome'].result.priority.value}",
                "Category": q["outcome"].result.category.value,
                "Owner": q["outcome"].result.owner.value,
                "Summary": q["outcome"].result.summary,
                "Respond": q["outcome"].response_target,
                "Channel": q["channel"],
                "Flags": ", ".join(f.value.replace("_", " ") for f in q["outcome"].result.flags),
            }
            for q in ordered
        ]
        st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
            column_config={"Summary": st.column_config.TextColumn(width="large")},
        )

        labels = [
            f"{i + 1}. {PRIORITY_ICON[q['outcome'].result.priority.value]} "
            f"{q['outcome'].result.summary[:80]}"
            for i, q in enumerate(ordered)
        ]
        pick = st.selectbox("Open a request", range(len(ordered)), format_func=lambda i: labels[i])
        chosen = ordered[pick]
        with st.container(border=True):
            st.markdown("**Original request**")
            st.markdown(f"> {chosen['text']}")
            render_outcome(chosen["outcome"], key=f"queue_{abs(hash((chosen['text'], chosen['channel'])))}")
