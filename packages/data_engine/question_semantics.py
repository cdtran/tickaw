"""Conservative checks that a valid plan measures the concept asked about."""

import re
from dataclasses import dataclass

from packages.data_engine.query_plan import QueryPlan, RowCount


@dataclass(frozen=True)
class MeaningIssue:
    code: str
    concept: str
    message: str
    plan_measure: str

    def diagnostic(self) -> dict:
        return {
            "code": self.code,
            "concept": self.concept,
            "plan_measure": self.plan_measure,
        }


CONCEPT_PATTERNS = {
    "quantity": (
        re.compile(r"\b(?:quantity|quantities|units?)\b", re.IGNORECASE),
        re.compile(
            r"\b(?:number of|how many)\s+(?:books?|items?|products?)\s+(?:were\s+)?sold\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bsold\s+(?:the\s+)?most\s+(?:books?|items?|products?)\b", re.IGNORECASE),
    ),
    "profit": (re.compile(r"\b(?:profit|margin)\b", re.IGNORECASE),),
    "price": (re.compile(r"\b(?:price|prices)\b", re.IGNORECASE),),
    "customer": (re.compile(r"\bcustomers?\b", re.IGNORECASE),),
}

CONCEPT_COLUMN_TOKENS = {
    "quantity": {"quantity", "qty", "units", "unit_count", "items_sold", "books_sold"},
    "profit": {"profit", "margin", "profit_margin", "cost"},
    "price": {"price", "unit_price"},
    "customer": {"customer", "customer_id", "buyer", "buyer_id"},
}


def requested_concepts(question: str) -> set[str]:
    return {
        concept
        for concept, patterns in CONCEPT_PATTERNS.items()
        if any(pattern.search(question) for pattern in patterns)
    }


def concept_columns(concept: str, catalog: dict[str, str]) -> set[str]:
    tokens = CONCEPT_COLUMN_TOKENS[concept]
    return {name for name in catalog if name.casefold() in tokens}


def plan_measure(plan: QueryPlan) -> str:
    measures = []
    for metric in plan.metrics:
        if isinstance(metric, RowCount):
            measures.append("row_count")
        else:
            measures.append(metric.column)
    return ",".join(measures)


def check_question_meaning(
    question: str,
    plan: QueryPlan,
    catalog: dict[str, str],
    clarification: str | None = None,
) -> MeaningIssue | None:
    """Reject only explicit business measures absent from the schema.

    This deliberately does not attempt general natural-language equivalence. It prevents a
    small set of high-confidence substitutions while leaving uncertain wording to the model.
    """
    clarification_text = (clarification or "").casefold()
    explicit_row_count = bool(
        re.search(r"\b(?:row|rows|record|records|transaction|transactions)\b", clarification_text)
        and re.search(r"\b(?:count|counting|use)\b", clarification_text)
    )
    measured_columns = {
        metric.column for metric in plan.metrics if not isinstance(metric, RowCount)
    }
    for concept in sorted(requested_concepts(question)):
        available = concept_columns(concept, catalog)
        if not available:
            if explicit_row_count and any(isinstance(metric, RowCount) for metric in plan.metrics):
                continue
            if any(column.casefold() in clarification_text for column in measured_columns):
                continue
            return MeaningIssue(
                code="MISSING_MEASURE",
                concept=concept,
                plan_measure=plan_measure(plan),
                message=(
                    f"The question asks for {concept}, but this dataset has no recognized "
                    f"{concept} field. Row count and other measures cannot be substituted."
                ),
            )
        if not measured_columns.intersection(available):
            return MeaningIssue(
                code="SEMANTIC_SUBSTITUTION",
                concept=concept,
                plan_measure=plan_measure(plan),
                message=(
                    f"The question asks for {concept}, but the plan measures a different concept."
                ),
            )
    return None
