"""Deterministic keyword rules.

Two jobs:
1. rule_based_triage(): a fallback classifier so the tool still returns a
   usable result when the AI provider is down, rate-limited or not configured.
2. apply_guardrails(): safety floors applied to EVERY result (AI or rules).
   The LLM makes the judgment call; the rules make sure a few critical cases
   (data exposure, outages, prompt injection, invented prices) never slip through.

The keyword lists are intentionally simple and transparent. They are a
safety net, not the primary classifier.
"""

import re
from dataclasses import dataclass, field

from .schema import (
    DEFAULT_OWNER,
    RESPONSE_TARGET,
    Category,
    Flag,
    Priority,
    TriageResult,
)

# ---------------------------------------------------------------- keyword lists
DATA_EXPLICIT = [
    r"\bbreach(ed)?\b", r"\bleak(ed|s)?\b", r"\bexposed\b", r"\bexposure\b",
    r"\bunauthori[sz]ed access\b", r"\bcompromised\b", r"\bhacked\b",
]
DATA_MISTAKE = [
    r"\baccidentally\b", r"\bby mistake\b", r"\bmistakenly\b",
    r"\bwrong (workspace|folder|person|recipient|client|account|email|channel)\b",
    r"\bshould ?n[o']?t have access\b",
]
DATA_SENSITIVE = [
    r"\bcustomers?\b", r"\bcontact (information|details)\b", r"\bpersonal\b",
    r"\bconfidential\b", r"\bpii\b", r"\bspreadsheet\b", r"\brecords?\b",
    r"\bdata\b", r"\bpasswords?\b", r"\bapi keys?\b", r"\bcredentials\b",
]
OUTAGE = [
    r"\bunavailable\b", r"\b(is|are|went|been|was) down\b", r"\boutage\b",
    r"\bcan(no|')?t (access|log ?in|open|use)\b",
    r"\bunable to (access|log ?in|open|use)\b",
    r"\bnot (loading|working|responding)\b", r"\bstopped working\b",
    r"\bcrash(ed|es|ing)?\b",
]
SEVERITY = [
    r"\bas soon as possible\b", r"\basap\b", r"\bimmediate(ly)?\b", r"\bemergency\b",
    r"\bcritical\b", r"\burgent(ly)?\b", r"\bsince (this morning|yesterday|last night)\b",
    r"\b(all|our) (staff|users|team|employees)\b", r"\bstaff cannot\b",
    r"\bcustomers? (are )?waiting\b", r"\bproduction\b",
]
LOW_SIGNALS = [
    r"\bno deadline\b", r"\bno rush\b", r"\bwhenever\b",
    r"\bwhen you (get|have) (a )?(chance|moment|minute|time)\b",
    r"\bfuture (update|release|version|roadmap)\b", r"\bnice to have\b",
    r"\bideas?\b", r"\bsuggestions?\b", r"\bfeedback\b", r"\bjust wanted to\b",
]
DEADLINE = [
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\bdeadline\b", r"\bdue (on|by|date)\b", r"\bnext week\b", r"\btoday\b",
    r"\btomorrow\b", r"\bend of (the )?(day|week|month)\b", r"\beod\b",
]
FRUSTRATION = [
    r"\b(second|third|fourth) time\b", r"\bstill (not|no|waiting)\b",
    r"\b(nobody|no one) (has )?(replied|responded|answered|got back)\b",
    r"\b(disappointed|frustrated|unacceptable|furious|angry)\b",
]
INJECTION = [
    r"\bignore (all |any )?(the )?(previous|prior|above|earlier|your) (instructions|rules|prompts?)\b",
    r"\bdisregard (all |any )?(the )?(previous|prior|above|your)\b",
    r"\bsystem prompt\b", r"\byou are now\b",
    r"\b(classify|mark|label|route|set) (this|it|the request) (as|to)\b",
]
SPAM = [
    r"\bcongratulations\b", r"\bclick here\b", r"\bclaim (your|it|now)\b",
    r"\b\d{2}% off\b", r"\bexclusive (offer|deal|package)\b", r"\bseo\b", r"\bwinner\b",
]
MULTI_MARKERS = [r"\b(two|several|a few|couple of) (things|issues|questions)\b", r"\bseparately\b"]

# (pattern, weight) per category
CATEGORY_KEYWORDS = {
    Category.BILLING: [
        (r"\binvoices?\b", 2), (r"\bbill(s|ing|ed)?\b", 1), (r"\bcharged?\b", 1),
        (r"\bcharged twice\b", 1), (r"\bpayments?\b", 1), (r"\brefunds?\b", 2),
        (r"\bovercharg", 2), (r"\breceipts?\b", 1), (r"\bcredit note\b", 2),
    ],
    Category.SALES: [
        (r"\bpric(e|es|ing)\b", 2), (r"\bquotes?\b", 2), (r"\bproposal\b", 2),
        (r"\bhow much\b", 2), (r"\binterested in\b", 1.5), (r"\bdemo\b", 1),
        (r"\bcustom\b", 1), (r"\bautomat(e|ed|ion)\b", 1.5), (r"\btimeline\b", 0.5),
        (r"\b(speak|talk|meeting|meet)\b", 0.5), (r"\b(purchase|buy)\b", 1),
        (r"\b(more|additional|extra) (seats|licen[cs]es|users)\b", 2),
    ],
    Category.TECHNICAL: [
        (r"\bportal\b", 1), (r"\bdashboard\b", 1), (r"\blog ?in\b", 1), (r"\bbugs?\b", 2),
        (r"\berrors?\b", 1.5), (r"\bintegrations?\b", 1), (r"\bapi\b", 1),
        (r"\bfeatures?\b", 1), (r"\bdark mode\b", 1.5), (r"\bfonts?\b", 1),
        (r"\bsync(ing)?\b", 1), (r"\bexport(s|ing)?\b", 1), (r"\bslow(ly)?\b", 1),
        (r"\bworkspace\b", 0.5),
    ],
    Category.SUPPORT: [
        (r"\bhow (do|can) (i|we)\b", 2), (r"\bhow to\b", 1.5), (r"\btraining\b", 1.5),
        (r"\bonboarding\b", 1.5), (r"\bpassword reset\b", 2),
        (r"\badd (a )?(new )?(user|colleague|team member)\b", 2), (r"\bpermissions?\b", 1),
        (r"\blogo\b", 1), (r"\baccount\b", 0.5),
    ],
}

# Lines in drafts that look like a price or amount, used to catch invented numbers.
MONEY = re.compile(r"(?:[$€£₹]\s?\d[\d,.]*|\b\d[\d,.]*\s?(?:usd|eur|gbp|dollars|euros)\b)", re.I)
INVOICE_ID = re.compile(r"\b[A-Z]{2,5}-\d{2,}\b")
QUANTITY = re.compile(
    r"\b\d+\s+(?:employees|users|people|staff|seats|licen[cs]es|systems|locations|offices)\b", re.I
)


def _hits(patterns, text):
    return [m.group(0) for p in patterns for m in [re.search(p, text, re.I)] if m]


@dataclass
class Signals:
    data_exposure: list[str] = field(default_factory=list)
    outage: list[str] = field(default_factory=list)
    severity: list[str] = field(default_factory=list)
    low: list[str] = field(default_factory=list)
    deadline: list[str] = field(default_factory=list)
    frustration: list[str] = field(default_factory=list)
    injection: list[str] = field(default_factory=list)
    spam: list[str] = field(default_factory=list)
    multi: list[str] = field(default_factory=list)
    scores: dict = field(default_factory=dict)


def detect(text: str) -> Signals:
    s = Signals()
    explicit = _hits(DATA_EXPLICIT, text)
    mistake, sensitive = _hits(DATA_MISTAKE, text), _hits(DATA_SENSITIVE, text)
    s.data_exposure = explicit or (mistake + sensitive if mistake and sensitive else [])
    s.outage = _hits(OUTAGE, text)
    s.severity = _hits(SEVERITY, text)
    s.low = _hits(LOW_SIGNALS, text)
    s.deadline = _hits(DEADLINE, text)
    s.frustration = _hits(FRUSTRATION, text)
    s.injection = _hits(INJECTION, text)
    s.spam = _hits(SPAM, text)
    s.multi = _hits(MULTI_MARKERS, text)
    s.scores = {
        cat: sum(w for p, w in kws if re.search(p, text, re.I))
        for cat, kws in CATEGORY_KEYWORDS.items()
    }
    return s


def _quote(words):
    return ", ".join(f"'{w.lower()}'" for w in dict.fromkeys(words))


# ---------------------------------------------------------------- fallback classifier
def rule_based_triage(text: str) -> TriageResult:
    s = detect(text)
    ranked = sorted(s.scores.items(), key=lambda kv: kv[1], reverse=True)
    (top_cat, top_score), (second_cat, second_score) = ranked[0], ranked[1]
    flags: list[Flag] = []

    # Category
    if s.data_exposure or s.outage:
        category = Category.TECHNICAL
        cat_reason = f"Access or data problem detected ({_quote(s.data_exposure or s.outage)})."
    elif s.spam:
        category = Category.OTHER
        cat_reason = f"Looks like unsolicited marketing ({_quote(s.spam)})."
    elif top_score > 0:
        category = top_cat
        cat_reason = f"Strongest keyword match for {top_cat.value} (score {top_score:g})."
    else:
        category = Category.OTHER
        cat_reason = "No clear business category keywords found."

    # Flags
    if s.data_exposure:
        flags.append(Flag.DATA_EXPOSURE)
    if s.outage:
        flags.append(Flag.SERVICE_OUTAGE)
    if s.deadline:
        flags.append(Flag.DEADLINE)
    if s.frustration:
        flags.append(Flag.UPSET_CUSTOMER)
    if s.injection or s.spam:
        flags.append(Flag.SUSPICIOUS)
    if top_score >= 1 and second_score >= 1 and (s.multi or min(top_score, second_score) >= 2):
        flags.append(Flag.MULTIPLE_ISSUES)
    if len(text.split()) < 6 or (top_score == 0 and not (s.data_exposure or s.outage or s.spam)):
        flags.append(Flag.AMBIGUOUS)

    # Priority
    if s.data_exposure:
        priority, why = Priority.URGENT, f"Possible exposure of sensitive data ({_quote(s.data_exposure)})."
    elif s.outage and s.severity:
        priority, why = Priority.URGENT, f"Service outage blocking work ({_quote(s.outage + s.severity)})."
    elif s.outage:
        priority, why = Priority.HIGH, f"Service problem reported ({_quote(s.outage)})."
    elif s.frustration:
        priority, why = Priority.HIGH, f"Frustrated client, risk to the relationship ({_quote(s.frustration)})."
    elif category == Category.BILLING and s.deadline:
        priority, why = Priority.HIGH, f"Billing issue with a deadline ({_quote(s.deadline)})."
    elif s.spam:
        priority, why = Priority.LOW, "Unsolicited message, no client action needed."
    elif s.low:
        priority, why = Priority.LOW, f"No time pressure indicated ({_quote(s.low)})."
    elif category == Category.OTHER:
        priority, why = Priority.LOW, "No clear request or business impact."
    else:
        priority, why = Priority.MEDIUM, "Genuine business need without immediate impact."

    owner = DEFAULT_OWNER[category]
    confidence = 0.7 if (s.data_exposure or s.outage) else 0.6 if top_score - second_score >= 2 else 0.45

    return TriageResult(
        summary=_extractive_summary(text),
        key_details=extract_key_details(text),
        category_reason=cat_reason,
        category=category,
        priority_reason=why,
        priority=priority,
        routing_reason=f"Default owner for {category.value} requests.",
        owner=owner,
        flags=flags,
        confidence=confidence,
        draft_response=_template_draft(text, category, priority, flags),
    )


def _extractive_summary(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    words = " ".join(sentences[:2]).split()
    return " ".join(words[:40]) + ("..." if len(words) > 40 else "")


def extract_key_details(text: str) -> list[str]:
    details = [f"Reference: {m}" for m in dict.fromkeys(INVOICE_ID.findall(text))]
    details += [f"Scale: {m}" for m in dict.fromkeys(QUANTITY.findall(text))]
    details += [f"Timing: {m}" for m in dict.fromkeys(_hits(DEADLINE, text))]
    details += [f"Amount: {m}" for m in dict.fromkeys(MONEY.findall(text))]
    return details[:6]


def _template_draft(text: str, category: Category, priority: Priority, flags: list[Flag]) -> str:
    sign_off = "\n\nBest regards,\n[Your Name]"
    target = RESPONSE_TARGET[priority]

    if Flag.DATA_EXPOSURE in flags:
        body = (
            "Thank you for letting us know so quickly - we are treating this as urgent. "
            "Our Engineering team has been alerted and will work with you to remove access "
            "to the file as a priority.\n\n"
            "To help us act fast, please reply with:\n"
            "- the name of the workspace the file was uploaded to\n"
            "- the file name and approximate time of upload\n"
            "- who currently has access to that workspace, if known\n\n"
            "In the meantime, please avoid sharing or downloading the file further. "
            "We will update you by [time]."
        )
    elif Flag.SERVICE_OUTAGE in flags:
        body = (
            "Thank you for reporting this - we understand your team is blocked and our "
            "Engineering team is investigating now.\n\n"
            "To help us narrow it down, could you share:\n"
            "- any error message or screenshot your staff are seeing\n"
            "- when the problem started and whether all users are affected\n\n"
            "We will send you an update by [time] and keep you informed until access is restored."
        )
    elif Flag.SUSPICIOUS in flags and category == Category.OTHER:
        return "[No reply recommended: this message looks like unsolicited marketing or spam. Archive or mark as spam.]"
    elif category == Category.BILLING:
        refs = INVOICE_ID.findall(text)
        ref = f" regarding invoice {refs[0]}" if refs else ""
        when = " before your payment date" if Flag.DEADLINE in flags else ""
        body = (
            f"Thank you for flagging this{ref}. I have passed it to our Finance team, who will "
            f"review the charges{when} and confirm the outcome with you.\n\n"
            "If you have any supporting details, such as the specific line items in question, "
            "please reply to this email so we can resolve it quickly."
        )
    elif category == Category.SALES:
        body = (
            "Thank you for reaching out and for your interest in working with us. I have shared "
            "your message with our Sales team, who will be in touch to learn more about your goals.\n\n"
            "The best next step is a short discovery call so we can understand your current setup "
            "and requirements before discussing options, pricing and timelines. Could you share a "
            "few times that work for you, or book directly here: [calendar link]?"
        )
    elif category == Category.TECHNICAL and priority == Priority.LOW:
        body = (
            "Thank you for the suggestions - we appreciate you taking the time to share them. "
            "I have logged your request with our Engineering team so it can be considered in "
            "future planning.\n\n"
            "We cannot commit to a timeline yet, but we will let you know if it is scheduled. "
            "If you have any other ideas, feel free to send them over."
        )
    elif category == Category.TECHNICAL:
        body = (
            "Thank you for reporting this. I have passed it to our Engineering team, who will "
            "look into it.\n\nCould you share any error messages, screenshots and the steps that "
            f"lead to the issue? We will follow up {target}."
        )
    elif category == Category.SUPPORT:
        sorry = " and I am sorry for the delay in getting back to you" if Flag.UPSET_CUSTOMER in flags else ""
        body = (
            f"Thank you for getting in touch{sorry}. Our Client Success team is looking into "
            f"your request and will follow up with you {target}.\n\n"
            "If there are any additional details that would help, such as account names or "
            "screenshots, please reply to this email."
        )
    else:
        body = (
            "Thank you for your message. So that we can direct it to the right person, could you "
            "share a little more detail about what you need help with? Our Client Success team "
            f"will follow up {target}."
        )
    return f"Hi [Client Name],\n\n{body}{sign_off}"


# ---------------------------------------------------------------- guardrails
def apply_guardrails(text: str, result: TriageResult) -> tuple[TriageResult, list[str]]:
    """Enforce safety floors and collect notes for the human reviewer."""
    s = detect(text)
    notes: list[str] = []
    update: dict = {}
    flags = list(result.flags)
    priority = result.priority

    if s.data_exposure and Flag.DATA_EXPOSURE not in flags:
        flags.append(Flag.DATA_EXPOSURE)
    if Flag.DATA_EXPOSURE in flags and priority != Priority.URGENT:
        notes.append(f"Guardrail raised priority {priority.value} -> Urgent: possible data exposure.")
        priority = Priority.URGENT
    if s.outage and priority.rank < Priority.HIGH.rank:
        notes.append(f"Guardrail raised priority {priority.value} -> High: service outage keywords.")
        priority = Priority.HIGH
        if Flag.SERVICE_OUTAGE not in flags:
            flags.append(Flag.SERVICE_OUTAGE)
    if s.injection and Flag.SUSPICIOUS not in flags:
        flags.append(Flag.SUSPICIOUS)

    if Flag.DATA_EXPOSURE in flags:
        notes.append("Possible data exposure: loop in your security/privacy lead before replying.")
    if Flag.SUSPICIOUS in flags:
        notes.append("Suspicious content (spam or instructions aimed at the AI) - verify before acting.")
    if Flag.MULTIPLE_ISSUES in flags:
        notes.append("Several issues in one message - consider splitting into separate tickets.")
    if Flag.AMBIGUOUS in flags:
        notes.append("Request is vague - confirm details with the client.")
    if Flag.UPSET_CUSTOMER in flags:
        notes.append("Client sounds frustrated - consider a personal follow-up.")

    invented = set(MONEY.findall(result.draft_response)) - set(MONEY.findall(text))
    if invented:
        notes.append(f"Draft mentions amounts not in the request ({', '.join(invented)}) - verify before sending.")
    if result.confidence < 0.6:
        notes.append(f"Low confidence ({result.confidence:.0%}) - double-check the labels.")
    if result.owner != DEFAULT_OWNER[result.category]:
        notes.append(
            f"Routed outside the default ({result.category.value} -> {result.owner.value}): "
            f"{result.routing_reason}"
        )

    if priority != result.priority:
        update["priority"] = priority
        update["priority_reason"] = result.priority_reason + " (Raised by safety guardrail.)"
    if flags != result.flags:
        update["flags"] = flags
    return (result.model_copy(update=update) if update else result), notes
