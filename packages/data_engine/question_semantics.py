"""Conservative checks that a valid plan measures the concept asked about."""

import re
from dataclasses import dataclass

from packages.data_engine.query_plan import Comparison, QueryPlan, RowCount


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


def active_record_count_issue(question, plan, catalog, clarification):
    """Evidence: active-records-by-category baseline counted non-null booleans.

    Match only an explicit count request and an optional known grouping column.
    Resumed clarification wording is outside this rule's narrow evidence base.
    """
    if catalog.get("active") != "boolean" or clarification:
        return None
    groups = "|".join(re.escape(name) for name in catalog)
    pattern = (
        r"(?:how many active records(?: are there| are)?|count(?: the)? active records)"
        rf"(?: (?:by|per|in each|for each) (?:{groups}))?[?.!]?"
    )
    if not re.fullmatch(pattern, question.strip(), re.IGNORECASE):
        return None
    if not any(isinstance(metric, RowCount) for metric in plan.metrics):
        return MeaningIssue(
            "SEMANTIC_SUBSTITUTION",
            "active_record_count",
            "Counting active records requires a row-count metric; non-null Boolean values "
            "include both true and false.",
            plan_measure(plan),
        )
    # Require one unambiguous active predicate; unrelated filters are outside this check.
    active_filters = [condition for condition in plan.filters if condition.column == "active"]
    if len(active_filters) == 1 and isinstance(active_filters[0], Comparison):
        condition = active_filters[0]
        if (condition.op == "eq" and condition.value is True) or (
            condition.op == "ne" and condition.value is False
        ):
            return None
    return MeaningIssue(
        "MISSING_REQUIRED_FILTER",
        "active_record_count",
        "Counting active records requires filtering the Boolean active field to true.",
        plan_measure(plan),
    )


def check_question_meaning(
    question: str,
    plan: QueryPlan,
    catalog: dict[str, str],
    clarification: str | None = None,
) -> MeaningIssue | None:
    """Reject explicit business-measure substitutions and narrow active-record counts.

    This deliberately does not attempt general natural-language equivalence. It prevents a
    small set of high-confidence substitutions while leaving uncertain wording to the model.
    """
    active_issue = active_record_count_issue(question, plan, catalog, clarification)
    if active_issue:
        return active_issue
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
