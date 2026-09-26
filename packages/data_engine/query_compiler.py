"""Compile validated v1 aggregate plans into SQLGlot nodes, never SQL fragments."""

from sqlglot import ErrorLevel, exp

from packages.data_engine.query_plan import (
    ColumnType,
    Comparison,
    NullCheck,
    RowCount,
    validate_plan,
)

COMPILER_VERSION = "1"
SUPPORTED_DIALECTS = frozenset({"duckdb"})
AGGREGATES = {
    "sum": exp.Sum,
    "avg": exp.Avg,
    "min": exp.Min,
    "max": exp.Max,
    "count_non_null": exp.Count,
}
COMPARISONS = {
    "eq": exp.EQ,
    "ne": exp.NEQ,
    "gt": exp.GT,
    "gte": exp.GTE,
    "lt": exp.LT,
    "lte": exp.LTE,
}


def column(name: str) -> exp.Column:
    # A dotted or SQL-looking header is one quoted identifier, not an expression.
    return exp.Column(this=exp.Identifier(this=name, quoted=True))


def literal(value, kind: ColumnType) -> exp.Expression:
    if kind == "boolean":
        return exp.Boolean(this=value)
    if kind in {"integer", "number"}:
        return exp.Literal.number(value)
    node = exp.Literal.string(value)
    if kind == "date":
        return exp.Cast(this=node, to=exp.DataType(this=exp.DataType.Type.DATE))
    return node


def build_ast(payload: dict, columns: dict[str, ColumnType]) -> exp.Select:
    """Revalidate at the compiler boundary; source is a server-registered relation.

    An execution adapter must register only the pinned dataset as `dataset`.
    This function builds a tree and performs no execution or I/O.
    """
    plan = validate_plan(payload, columns)
    selections = [column(name) for name in plan.dimensions]
    for metric in plan.metrics:
        aggregate = (
            exp.Count(this=exp.Star())
            if isinstance(metric, RowCount)
            else AGGREGATES[metric.op](this=column(metric.column))
        )
        selections.append(
            exp.Alias(
                this=aggregate,
                alias=exp.Identifier(this=metric.alias, quoted=True),
            )
        )
    query = exp.Select(expressions=selections).from_(
        exp.Table(this=exp.Identifier(this="dataset", quoted=True)),
    )
    predicates = []
    for condition in plan.filters:
        if isinstance(condition, NullCheck):
            predicate = exp.Is(this=column(condition.column), expression=exp.Null())
            if condition.op == "is_not_null":
                predicate = exp.Not(this=predicate)
        elif isinstance(condition, Comparison):
            predicate = COMPARISONS[condition.op](
                this=column(condition.column),
                expression=literal(condition.value, columns[condition.column]),
            )
        predicates.append(predicate)
    if predicates:
        predicate = predicates[0]
        for other in predicates[1:]:
            predicate = exp.And(this=predicate, expression=other)
        query = query.where(predicate)
    if plan.dimensions:
        query = query.group_by(*(column(name) for name in plan.dimensions))

    # Grouping keys uniquely identify output rows; append keys as stable tie breakers.
    orderings = [(item.field, item.direction) for item in plan.order_by]
    ordered_fields = {name for name, _ in orderings}
    orderings.extend((name, "asc") for name in plan.dimensions if name not in ordered_fields)
    if orderings:
        query = query.order_by(
            *(
                exp.Ordered(this=column(name), desc=direction == "desc", nulls_first=False)
                for name, direction in orderings
            )
        )
    return query.limit(exp.Literal.number(plan.limit))


def compile_sql(payload: dict, columns: dict[str, ColumnType], *, dialect="duckdb") -> str:
    """Only dialects with execution coverage are accepted in this milestone."""
    if dialect not in SUPPORTED_DIALECTS:
        raise ValueError(f"Untested query-plan dialect: {dialect}")
    return build_ast(payload, columns).sql(
        dialect=dialect,
        unsupported_level=ErrorLevel.RAISE,
    )
