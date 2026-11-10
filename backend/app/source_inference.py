"""Optional advice from LiteLLM. SQL verification remains authoritative."""

import os
from typing import Literal

from pydantic import Field

from .contracts import Contract
from .provider import ProviderFailure
from .source_parse import entry


class Refined(Contract):
    category: Literal[
        "identity_lookup",
        "academic_record_lookup",
        "curriculum_lookup",
        "preference_lookup",
        "goal_lookup",
        "persona_lookup",
        "course_lookup",
        "analytical_question",
        "general_conversation",
    ]
    relation: str = Field(max_length=40)
    semantic_query: str = Field(min_length=1, max_length=400)


class AcademicTriple(Contract):
    relation: Literal["HAS_PREREQUISITE", "EQUIVALENT_TO", "HAS_REQUIREMENT"]
    subject: str = Field(min_length=1, max_length=90)
    value: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=5, max_length=600)
    page: int = Field(ge=1)


class Triples(Contract):
    triples: list[AcademicTriple] = Field(max_length=16)


def refine(provider, q):
    from .knowledge import RELATIONS

    if not provider.enabled:
        return None
    try:
        proposal = provider.complete(
            "Map the question to an educational retrieval intent. Only these relation names are available: "
            + ", ".join(RELATIONS)
            + ". Supply a search phrase. No Cypher.",
            {"question": q},
            Refined,
        )
        if isinstance(proposal, Refined) and proposal.relation in RELATIONS:
            return proposal
    except ProviderFailure:
        pass
    return None


def extract(provider, pages, kind):
    if (
        not provider.enabled
        or os.getenv("SOURCE_LLM_ENABLED", "false").lower() != "true"
        or kind not in ("curriculum_template", "general_academic_document")
    ):
        return [], []
    supplied = [{"page": p["page"], "text": p["text"][:3000]} for p in pages[:5] if not p["review"]]
    try:
        result = provider.complete(
            "Propose explicitly printed academic reference relationships. Copy the exact quotation, endpoints and page. Exclude learner-specific claims.",
            supplied,
            Triples,
        )
    except ProviderFailure:
        return [], ["Optional narrative extraction failed. Deterministic results retained."]
    rows = []
    for t in result.triples if isinstance(result, Triples) else []:
        if not any(p["page"] == t.page and t.quote in p["text"] for p in supplied) or any(
            v not in t.quote for v in (t.subject, t.value)
        ):
            continue
        # A quotation alone cannot establish direction. Stage all narrative proposals for review.
        rows.append(
            entry(
                "narrative_relation",
                t.value,
                f"page {t.page}, model proposal {len(rows) + 1}",
                "model_proposal",
                "review",
                t.relation,
                t.subject,
                t.quote,
                page=t.page,
            )
        )
    return rows, []
