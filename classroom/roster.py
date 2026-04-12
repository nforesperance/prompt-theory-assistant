"""Roster parsing & validation.

Accepts CSV or JSON. Rejects malformed rosters with clear errors so
teachers can fix them in Excel/Sheets before retrying.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

REQUIRED_COLUMNS = {"student_id", "display_name"}
OPTIONAL_COLUMNS = {
    "grade_level",
    "reading_level",
    "language",
    "accommodations",
    "notes",
}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS

ALLOWED_ACCOMMODATIONS = {
    "extra_time",
    "simplified_language",
    "visual_supports",
    "screen_reader",
    "translation",
}

ALLOWED_READING_LEVELS = {"below_grade", "at_grade", "above_grade"}


class RosterError(ValueError):
    """Raised when a roster is malformed."""


def _validate_row(row: dict, row_num: int) -> dict:
    missing = REQUIRED_COLUMNS - set(k for k, v in row.items() if v not in (None, ""))
    if missing:
        raise RosterError(f"Row {row_num}: missing required columns {sorted(missing)}")

    clean: dict[str, Any] = {
        "student_id": str(row["student_id"]).strip(),
        "display_name": str(row["display_name"]).strip(),
    }

    if row.get("grade_level") not in (None, ""):
        try:
            clean["grade_level"] = int(row["grade_level"])
        except (ValueError, TypeError):
            raise RosterError(f"Row {row_num}: grade_level must be an integer")
        if not 1 <= clean["grade_level"] <= 12:
            raise RosterError(f"Row {row_num}: grade_level must be between 1 and 12")

    if row.get("reading_level"):
        rl = str(row["reading_level"]).strip().lower()
        if rl not in ALLOWED_READING_LEVELS:
            raise RosterError(
                f"Row {row_num}: reading_level must be one of {sorted(ALLOWED_READING_LEVELS)}"
            )
        clean["reading_level"] = rl

    if row.get("language"):
        clean["language"] = str(row["language"]).strip().lower()[:5]

    if row.get("accommodations"):
        items = [a.strip().lower() for a in str(row["accommodations"]).split(";") if a.strip()]
        invalid = [a for a in items if a not in ALLOWED_ACCOMMODATIONS]
        if invalid:
            raise RosterError(
                f"Row {row_num}: unknown accommodations {invalid}. "
                f"Allowed: {sorted(ALLOWED_ACCOMMODATIONS)}"
            )
        clean["accommodations"] = ";".join(items)

    if row.get("notes"):
        notes = str(row["notes"]).strip()
        if len(notes) > 500:
            raise RosterError(f"Row {row_num}: notes exceed 500 characters")
        clean["notes"] = notes

    return clean


def parse_csv(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise RosterError("CSV has no header row")

    unknown = set(reader.fieldnames) - ALLOWED_COLUMNS
    if unknown:
        raise RosterError(
            f"Unknown columns {sorted(unknown)}. "
            f"Allowed: {sorted(ALLOWED_COLUMNS)}"
        )

    rows = [_validate_row(row, i) for i, row in enumerate(reader, start=2)]
    _check_unique_ids(rows)
    return rows


def parse_json(content: str) -> list[dict]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise RosterError(f"Invalid JSON: {e}")

    if not isinstance(data, list):
        raise RosterError("JSON roster must be a list of student objects")

    rows = [_validate_row(row, i) for i, row in enumerate(data, start=1)]
    _check_unique_ids(rows)
    return rows


def parse(content: str, filename: str) -> list[dict]:
    if filename.lower().endswith(".csv"):
        return parse_csv(content)
    if filename.lower().endswith(".json"):
        return parse_json(content)
    raise RosterError(f"Unsupported file type: {filename}. Use .csv or .json")


def _check_unique_ids(rows: list[dict]) -> None:
    seen = set()
    for r in rows:
        sid = r["student_id"]
        if sid in seen:
            raise RosterError(f"Duplicate student_id: {sid}")
        seen.add(sid)
