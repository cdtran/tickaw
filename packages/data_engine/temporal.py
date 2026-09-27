"""Shared conservative temporal parsing for ingestion and query filter validation."""

import re
from datetime import UTC, date, datetime

DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}"
    r"(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})?\Z"
)


def parse_temporal(value: str) -> tuple[str, date | datetime]:
    """Parse unambiguous ISO dates/timestamps without guessing locale or timezone.

    Offset timestamps become UTC; naive timestamps stay naive. Precision above
    microseconds is rejected rather than silently truncated by Python or DuckDB.
    """
    if DATE.fullmatch(value):
        return "date", date.fromisoformat(value)
    match = TIMESTAMP.fullmatch(value)
    if not match:
        raise ValueError("Expected an ISO date or timestamp with at most six fractional digits")
    offset = match.group("offset")
    if (
        offset
        and offset != "Z"
        and (int(offset[1:3]) > 23 or int(offset[4:]) > 59 or offset == "-00:00")
    ):
        raise ValueError("Invalid or unspecified timestamp offset")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return "timestamp", parsed
    return "timestamp_tz", parsed.astimezone(UTC)
