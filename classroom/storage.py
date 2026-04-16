"""SQLite persistence for classroom deployment.

Single-file DB. All writes go through this module so swapping to Postgres
later is a one-file change.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("CLASSROOM_DB", "data/classroom.db"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    email          TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_email     TEXT NOT NULL REFERENCES teachers(email),
    name              TEXT NOT NULL,
    session_code      TEXT NOT NULL UNIQUE,
    topic             TEXT,
    theory            TEXT NOT NULL,
    provider          TEXT NOT NULL DEFAULT 'openai',
    model             TEXT,
    adaptive_routing  INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    class_id       INTEGER NOT NULL REFERENCES classes(id),
    student_id     TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    grade_level    INTEGER,
    reading_level  TEXT,
    language       TEXT DEFAULT 'en',
    accommodations TEXT,
    notes          TEXT,
    PRIMARY KEY (class_id, student_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id        INTEGER NOT NULL REFERENCES classes(id),
    student_id      TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    state_json      TEXT NOT NULL,
    transcript_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_class_student
    ON sessions(class_id, student_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)
        _migrate(c)


def _migrate(c) -> None:
    """Add columns that were introduced after initial release."""
    cols = {row["name"] for row in c.execute("PRAGMA table_info(classes)")}
    if "provider" not in cols:
        c.execute("ALTER TABLE classes ADD COLUMN provider TEXT NOT NULL DEFAULT 'openai'")
    if "model" not in cols:
        c.execute("ALTER TABLE classes ADD COLUMN model TEXT")
    if "adaptive_routing" not in cols:
        c.execute(
            "ALTER TABLE classes ADD COLUMN adaptive_routing INTEGER NOT NULL DEFAULT 1"
        )


# ─── Teachers ──────────────────────────────────────────────────────────────

def create_teacher(email: str, name: str, password: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO teachers (email, name, password_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (email.lower(), name, _hash_password(password), _now()),
        )


def authenticate_teacher(email: str, password: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM teachers WHERE email = ?", (email.lower(),)
        ).fetchone()
    if row and _verify_password(password, row["password_hash"]):
        return {"email": row["email"], "name": row["name"]}
    return None


# ─── Classes ───────────────────────────────────────────────────────────────

def create_class(
    teacher_email: str,
    name: str,
    topic: str,
    theory: str,
    provider: str,
    model: str | None = None,
    adaptive_routing: bool = True,
) -> dict:
    session_code = secrets.token_urlsafe(4).upper().replace("_", "").replace("-", "")[:8]
    with connect() as c:
        cur = c.execute(
            "INSERT INTO classes (teacher_email, name, session_code, topic, theory, "
            "provider, model, adaptive_routing, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                teacher_email.lower(), name, session_code, topic, theory,
                provider, model or None, int(bool(adaptive_routing)), _now(),
            ),
        )
        return {"id": cur.lastrowid, "session_code": session_code}


def list_classes(teacher_email: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM classes WHERE teacher_email = ? ORDER BY created_at DESC",
            (teacher_email.lower(),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_class_by_code(session_code: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM classes WHERE session_code = ?", (session_code.upper(),)
        ).fetchone()
    return dict(row) if row else None


def get_class(class_id: int) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
    return dict(row) if row else None


# ─── Roster ────────────────────────────────────────────────────────────────

def replace_roster(class_id: int, students: list[dict]) -> int:
    with connect() as c:
        c.execute("DELETE FROM students WHERE class_id = ?", (class_id,))
        c.executemany(
            "INSERT INTO students (class_id, student_id, display_name, grade_level, "
            "reading_level, language, accommodations, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    class_id,
                    s["student_id"],
                    s["display_name"],
                    s.get("grade_level"),
                    s.get("reading_level"),
                    s.get("language", "en"),
                    s.get("accommodations"),
                    s.get("notes"),
                )
                for s in students
            ],
        )
        return len(students)


def get_student(class_id: int, student_id: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM students WHERE class_id = ? AND student_id = ?",
            (class_id, student_id),
        ).fetchone()
    return dict(row) if row else None


def list_roster(class_id: int) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM students WHERE class_id = ? ORDER BY student_id",
            (class_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ─── Sessions ──────────────────────────────────────────────────────────────

def start_session(class_id: int, student_id: str, initial_state: dict) -> int:
    now = _now()
    with connect() as c:
        cur = c.execute(
            "INSERT INTO sessions (class_id, student_id, started_at, updated_at, "
            "state_json, transcript_json) VALUES (?, ?, ?, ?, ?, ?)",
            (class_id, student_id, now, now, json.dumps(initial_state), "[]"),
        )
        return cur.lastrowid


def update_session(session_id: int, state: dict, transcript: list[dict]) -> None:
    with connect() as c:
        c.execute(
            "UPDATE sessions SET updated_at = ?, state_json = ?, transcript_json = ? "
            "WHERE id = ?",
            (_now(), json.dumps(state), json.dumps(transcript), session_id),
        )


def get_session(session_id: int) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["state"] = json.loads(d.pop("state_json"))
    d["transcript"] = json.loads(d.pop("transcript_json"))
    return d


def list_sessions(class_id: int) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT id, class_id, student_id, started_at, updated_at "
            "FROM sessions WHERE class_id = ? ORDER BY updated_at DESC",
            (class_id,),
        ).fetchall()
    return [dict(r) for r in rows]
