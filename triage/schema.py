"""Data model for a triage result.

The enums are the single source of truth for the allowed labels. Anything the
LLM returns is validated against them, so the UI can never show a category,
priority or owner that the business did not define.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Category(str, Enum):
    SALES = "Sales"
    SUPPORT = "Support"
    BILLING = "Billing"
    TECHNICAL = "Technical"
    OTHER = "Other"


class Priority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    URGENT = "Urgent"

    @property
    def rank(self) -> int:
        return ["Low", "Medium", "High", "Urgent"].index(self.value)


class Owner(str, Enum):
    SALES_TEAM = "Sales Team"
    CLIENT_SUCCESS = "Client Success"
    FINANCE = "Finance"
    ENGINEERING = "Engineering"


class Flag(str, Enum):
    DATA_EXPOSURE = "possible_data_exposure"
    SERVICE_OUTAGE = "service_outage"
    DEADLINE = "deadline"
    MULTIPLE_ISSUES = "multiple_issues"
    AMBIGUOUS = "ambiguous"
    UPSET_CUSTOMER = "upset_customer"
    SUSPICIOUS = "suspicious_content"


# Default routing. The model may deviate, but must explain why in routing_reason.
DEFAULT_OWNER = {
    Category.SALES: Owner.SALES_TEAM,
    Category.SUPPORT: Owner.CLIENT_SUCCESS,
    Category.BILLING: Owner.FINANCE,
    Category.TECHNICAL: Owner.ENGINEERING,
    Category.OTHER: Owner.CLIENT_SUCCESS,
}

# Target time to first response, shown to the team member.
RESPONSE_TARGET = {
    Priority.URGENT: "within 1 hour",
    Priority.HIGH: "same business day",
    Priority.MEDIUM: "within 1 business day",
    Priority.LOW: "within 3 business days",
}


def _match_enum(enum_cls, value):
    """Accept case/spacing variants like 'urgent' or 'sales_team'."""
    if isinstance(value, enum_cls):
        return value
    key = str(value).strip().lower().replace("_", " ").replace("-", " ")
    for member in enum_cls:
        if member.value.lower() == key:
            return member
    return value  # let pydantic raise a clear error


class TriageResult(BaseModel):
    """What the AI (or the fallback rules) must produce for every request.

    Field order matters: each *_reason comes before its label so the model
    writes its justification first and then commits to a label.
    """

    summary: str = Field(min_length=1)
    key_details: list[str] = Field(default_factory=list)
    category_reason: str = ""
    category: Category
    priority_reason: str = Field(min_length=1)
    priority: Priority
    routing_reason: str = ""
    owner: Owner
    flags: list[Flag] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    draft_response: str = Field(min_length=1)

    @field_validator("category", mode="before")
    @classmethod
    def _norm_category(cls, v):
        return _match_enum(Category, v)

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v):
        return _match_enum(Priority, v)

    @field_validator("owner", mode="before")
    @classmethod
    def _norm_owner(cls, v):
        return _match_enum(Owner, v)

    @field_validator("flags", mode="before")
    @classmethod
    def _norm_flags(cls, v):
        # Unknown flags are dropped instead of failing the whole result.
        allowed = {f.value for f in Flag}
        out = []
        for item in v or []:
            item = item.value if isinstance(item, Enum) else item
            key = str(item).strip().lower().replace(" ", "_")
            if key in allowed and key not in out:
                out.append(key)
        return out

    @field_validator("confidence", mode="before")
    @classmethod
    def _norm_confidence(cls, v):
        # Some models answer 85 instead of 0.85.
        v = float(v)
        return v / 100 if 1 < v <= 100 else v


class TriageOutcome(BaseModel):
    """A validated result plus how it was produced, for the UI and eval."""

    result: TriageResult
    engine: str  # e.g. "gemini:gemini-3.8-flash" or "rules"
    review_notes: list[str] = Field(default_factory=list)
    latency_ms: int = 0

    @property
    def response_target(self) -> str:
        return RESPONSE_TARGET[self.result.priority]

    @property
    def needs_attention(self) -> bool:
        return bool(self.review_notes)
