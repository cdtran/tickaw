"""Bounded CSV profiling. This module has no database or storage dependencies."""
import csv
import io
import json
import math
from pathlib import Path

import pandas as pd

PROFILER_VERSION = "csv-v2"
MAX_ROWS = 100_000
MAX_COLUMNS = 100
MAX_CELLS = 500_000
MAX_FIELD_CHARS = 16_384
PREVIEW_ROWS = 10
SAMPLE_VALUES = 5
DISPLAY_CHARS = 256


class ProfileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def display_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        return str(value)  # Preserve integer precision in browser JSON.
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, str) and len(value) > DISPLAY_CHARS:
        return value[:DISPLAY_CHARS] + "…"
    return value


def profile_csv(source: Path, parquet: Path, max_bytes: int) -> dict:
    if source.stat().st_size > max_bytes:
        raise ProfileError("FILE_TOO_LARGE", "CSV exceeds the upload size limit.")
    try:
        # newline="" preserves CRLF inside quoted fields as data.
        with source.open(encoding="utf-8-sig", newline="") as file:
            text = file.read()
    except UnicodeError as error:
        raise ProfileError("UNSUPPORTED_ENCODING", "Save the file as UTF-8 CSV and upload a new version.") from error
    if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise ProfileError("INVALID_CSV", "CSV contains binary control characters.")
    if text.lstrip().lower().startswith(("<!doctype html", "<html", "<?xml")):
        raise ProfileError("UNSUPPORTED_FORMAT", "This looks like HTML or XML. Export the table as comma-delimited CSV.")
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        document = None
    if isinstance(document, (dict, list)):
        raise ProfileError("UNSUPPORTED_FORMAT", "This is JSON, not CSV. Export the table as comma-delimited CSV.")
    csv.field_size_limit(MAX_FIELD_CHARS)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, [])
        if not header or any(not name.strip() for name in header):
            raise ProfileError("INVALID_HEADER", "Every column needs a nonempty header.")
        # Detect a consistently delimited table, rather than silently making it one column.
        # Quoted delimiter characters in a legitimate single-column file remain valid.
        if len(header) == 1:
            for delimiter in (";", "\t", "|"):
                candidate = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
                alternate_header = next(candidate, [])
                if len(alternate_header) <= 1:
                    continue
                sampled = []
                for row in candidate:
                    if row:
                        sampled.append(row)
                    if len(sampled) >= 10:
                        break
                if not sampled or all(len(row) == len(alternate_header) for row in sampled):
                    raise ProfileError("UNSUPPORTED_DELIMITER", "Use commas between columns; semicolon, tab and pipe delimiters are not supported.")
        if len(header) > MAX_COLUMNS or any(len(name) > 256 for name in header):
            raise ProfileError("COLUMN_LIMIT", "Use at most 100 columns and headers up to 256 characters.")
        if len(set(header)) != len(header):
            raise ProfileError("DUPLICATE_COLUMNS", "Column names must be unique. Rename repeated headers and upload a new version.")
        records = []
        for row in reader:
            if not row:  # Skip empty physical lines, but preserve quoted empty cells.
                continue
            if len(row) != len(header):
                raise ProfileError("INVALID_CSV", f"Data row {len(records) + 1} has {len(row)} fields; the header has {len(header)}. Check commas and quotes.")
            records.append(row)
            if len(records) > MAX_ROWS or len(records) * len(header) > MAX_CELLS:
                raise ProfileError("ROW_LIMIT", "CSV exceeds 100,000 rows or 500,000 cells. Split it into smaller files.")
    except csv.Error as error:
        if "field larger than field limit" in str(error):
            raise ProfileError("FIELD_LIMIT", "A CSV field exceeds 16,384 characters. Shorten the value or split the file.") from error
        raise ProfileError("INVALID_CSV", "CSV quoting is malformed. Check closing quotes and export the file again.") from error
    # One CSV parse establishes the rows, then pandas handles types and profiling.
    frame = pd.DataFrame(records, columns=header, dtype="string").replace("", pd.NA)

    schema = []
    columns = []
    for name in frame.columns:
        series = frame[name]
        values = series.dropna()
        kind = "string"
        if values.empty:
            kind = "unknown"
        elif values.str.fullmatch(r"(?i:true|false)").all():
            frame[name] = series.str.lower().map({"true": True, "false": False}).astype("boolean")
            kind = "boolean"
        elif values.str.fullmatch(r"-?(?:0|[1-9]\d*)").all():
            # Preserve leading-zero identifiers and out-of-range integers as text.
            if all(len(value.lstrip("-")) <= 19 and -(2**63) <= int(value) < 2**63
                   for value in values):
                frame[name] = series.astype("Int64")
                kind = "integer"
        elif values.str.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?").all():
            numeric = pd.to_numeric(series, errors="coerce")
            if numeric.dropna().map(math.isfinite).all() and numeric.notna().sum() == len(values):
                frame[name] = numeric.astype("Float64")
                kind = "number"
        schema.append({"name": name, "inferred_type": kind, "pandas_dtype": str(frame[name].dtype)})
        columns.append({"name": name, "null_count": int(frame[name].isna().sum()),
                        "sample_values": [display_value(value) for value in frame[name].dropna().head(SAMPLE_VALUES)]})

    preview = [{name: display_value(value) for name, value in record.items()}
               for record in frame.head(PREVIEW_ROWS).to_dict(orient="records")]
    # Parquet receives complete typed values; only metadata samples are truncated.
    frame.to_parquet(parquet, engine="pyarrow", index=False, compression="snappy")
    result = {
        "row_count": len(frame),
        "schema_json": {"version": 1, "columns": schema},
        "profile_json": {"profiler_version": PROFILER_VERSION, "row_count": len(frame),
                         "column_count": len(schema), "columns": columns,
                         "preview_limit": PREVIEW_ROWS, "sample_limit": SAMPLE_VALUES,
                         "display_character_limit": DISPLAY_CHARS,
                         "null_policy": "Empty fields only; literal NA, NULL and NaN are text.",
                         "type_policy": "Conservative boolean/integer/number inference; dates and ambiguous values stay strings."},
        "preview_json": preview,
    }
    json.dumps(result, allow_nan=False)
    return result
