"""Supabase-backed persistence for the classroom deployment.

Public API is deliberately identical to the previous SQLite version so
that callers (auth, orchestrator, app) need no changes. Migration from
SQLite to Supabase happened in one file.

Authentication is still handled in Python (PBKDF2 password hashes in
`teachers`) rather than Supabase Auth — keeps the surface area small
for a 6-person pilot and avoids requiring email SMTP config. Students
authenticate with a session code + student_id looked up against the
`students` roster.

All DB calls go through the service-role client, which bypasses RLS.
Authorisation is enforced in the Python caller (`classroom/auth.py`).
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client


# ─── Client ───────────────────────────────────────────────────────────────

_client: Client | None = None


def _get_client() -> Client:
    """Lazy singleton. Reads Supabase URL and service-role key from env."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_KEY")
        )
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set "
                "(in .env locally or in Streamlit secrets on cloud)."
            )
        _client = create_client(url, key)
    return _client


def init_db() -> None:
    """Kept for API parity with the old SQLite backend. Schema is
    provisioned by running `supabase/schema.sql` once in the Supabase
    SQL editor; there is nothing to do at runtime."""
    return None


# ─── Password hashing ─────────────────────────────────────────────────────

def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200_000
    ).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(_hash_password(password, salt), stored)


# ─── Teachers ──────────────────────────────────────────────────────────────

def create_teacher(email: str, name: str, password: str) -> None:
    sb = _get_client()
    sb.table("teachers").insert(
        {
            "email": email.lower(),
            "name": name,
            "password_hash": _hash_password(password),
        }
    ).execute()


def authenticate_teacher(email: str, password: str) -> dict | None:
    sb = _get_client()
    res = (
        sb.table("teachers")
        .select("email,name,password_hash")
        .eq("email", email.lower())
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    if _verify_password(password, row["password_hash"]):
        return {"email": row["email"], "name": row["name"]}
    return None


# ─── Classes ───────────────────────────────────────────────────────────────

def _make_session_code() -> str:
    return (
        secrets.token_urlsafe(4).upper().replace("_", "").replace("-", "")[:8]
    )


def create_class(
    teacher_email: str,
    name: str,
    topic: str,
    theory: str,
    provider: str,
    model: str | None = None,
    adaptive_routing: bool = True,
) -> dict:
    sb = _get_client()
    code = _make_session_code()
    res = (
        sb.table("classes")
        .insert(
            {
                "teacher_email": teacher_email.lower(),
                "name": name,
                "session_code": code,
                "topic": topic,
                "theory": theory,
                "provider": provider,
                "model": model,
                "adaptive_routing": bool(adaptive_routing),
            }
        )
        .execute()
    )
    return {"id": res.data[0]["id"], "session_code": code}


def list_classes(teacher_email: str) -> list[dict]:
    sb = _get_client()
    res = (
        sb.table("classes")
        .select("*")
        .eq("teacher_email", teacher_email.lower())
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def get_class_by_code(session_code: str) -> dict | None:
    sb = _get_client()
    res = (
        sb.table("classes")
        .select("*")
        .eq("session_code", session_code.upper())
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_class(class_id: int) -> dict | None:
    sb = _get_client()
    res = sb.table("classes").select("*").eq("id", class_id).limit(1).execute()
    return res.data[0] if res.data else None


def delete_class(class_id: int, teacher_email: str) -> bool:
    """Delete a class owned by `teacher_email`. Cascades to students
    and sessions via the FK constraint. Returns True if a row was
    deleted, False if no matching class (wrong owner or bad id)."""
    sb = _get_client()
    res = (
        sb.table("classes")
        .delete()
        .eq("id", class_id)
        .eq("teacher_email", teacher_email.lower())
        .execute()
    )
    return bool(res.data)


# ─── Roster ────────────────────────────────────────────────────────────────

def replace_roster(class_id: int, students: list[dict]) -> int:
    sb = _get_client()
    sb.table("students").delete().eq("class_id", class_id).execute()
    if not students:
        return 0
    rows = [
        {
            "class_id": class_id,
            "student_id": s["student_id"],
            "display_name": s["display_name"],
            "grade_level": s.get("grade_level"),
            "reading_level": s.get("reading_level"),
            "language": s.get("language", "en"),
            "accommodations": s.get("accommodations"),
            "notes": s.get("notes"),
        }
        for s in students
    ]
    sb.table("students").insert(rows).execute()
    return len(rows)


def get_student(class_id: int, student_id: str) -> dict | None:
    sb = _get_client()
    res = (
        sb.table("students")
        .select("*")
        .eq("class_id", class_id)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def list_roster(class_id: int) -> list[dict]:
    sb = _get_client()
    res = (
        sb.table("students")
        .select("*")
        .eq("class_id", class_id)
        .order("student_id")
        .execute()
    )
    return res.data or []


# ─── Sessions ──────────────────────────────────────────────────────────────

def start_session(class_id: int, student_id: str, initial_state: dict) -> int:
    sb = _get_client()
    res = (
        sb.table("sessions")
        .insert(
            {
                "class_id": class_id,
                "student_id": student_id,
                "state": initial_state,
                "transcript": [],
            }
        )
        .execute()
    )
    return res.data[0]["id"]


def update_session(session_id: int, state: dict, transcript: list[dict]) -> None:
    sb = _get_client()
    sb.table("sessions").update(
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "transcript": transcript,
        }
    ).eq("id", session_id).execute()


def get_session(session_id: int) -> dict | None:
    sb = _get_client()
    res = sb.table("sessions").select("*").eq("id", session_id).limit(1).execute()
    return res.data[0] if res.data else None


def list_sessions(class_id: int) -> list[dict]:
    sb = _get_client()
    res = (
        sb.table("sessions")
        .select("id,class_id,student_id,started_at,updated_at")
        .eq("class_id", class_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return res.data or []


def get_latest_session_for_student(
    class_id: int, student_id: str
) -> dict | None:
    """Return the most recent session for this (class, student) pair,
    or None if the student has never started one. Used to resume a
    long-lived session when a student re-enters the session code."""
    sb = _get_client()
    res = (
        sb.table("sessions")
        .select("*")
        .eq("class_id", class_id)
        .eq("student_id", student_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ─── Evaluations ───────────────────────────────────────────────────────────

def submit_evaluation(
    session_id: int,
    class_id: int,
    student_id: str,
    ratings: dict[str, int],
    notes: str | None,
) -> None:
    sb = _get_client()
    sb.table("evaluations").insert(
        {
            "session_id": session_id,
            "class_id": class_id,
            "student_id": student_id,
            "coherence": ratings["coherence"],
            "made_me_think": ratings["made_me_think"],
            "one_at_a_time": ratings["one_at_a_time"],
            "reuse": ratings["reuse"],
            "notes": notes or None,
        }
    ).execute()


def get_evaluation(session_id: int) -> dict | None:
    sb = _get_client()
    res = (
        sb.table("evaluations")
        .select("*")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def count_evaluations_for_student(student_id: str) -> int:
    sb = _get_client()
    res = (
        sb.table("evaluations")
        .select("session_id", count="exact")
        .eq("student_id", student_id)
        .execute()
    )
    return res.count or 0


def list_evaluations_for_class(class_id: int) -> list[dict]:
    sb = _get_client()
    res = (
        sb.table("evaluations")
        .select("*")
        .eq("class_id", class_id)
        .order("submitted_at", desc=True)
        .execute()
    )
    return res.data or []


# ─── Final responses ───────────────────────────────────────────────────────

def get_final_response(student_id: str) -> dict | None:
    sb = _get_client()
    res = (
        sb.table("final_responses")
        .select("*")
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def submit_final_response(
    student_id: str, differences: str, standout: str | None
) -> None:
    sb = _get_client()
    sb.table("final_responses").insert(
        {
            "student_id": student_id,
            "differences": differences,
            "standout": standout or None,
        }
    ).execute()
