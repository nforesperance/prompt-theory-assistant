"""Auth helpers for the classroom app.

Two flows:
- Teacher: email + password (hashed via PBKDF2 in storage).
- Student: session code + student_id lookup against the class roster.

For production (school SSO), swap teacher login for `st.login()` (native
OIDC). The rest of the app reads `st.session_state["auth"]` which is
agnostic to how the role was established.
"""

from __future__ import annotations

import streamlit as st

from classroom import storage


def current_auth() -> dict | None:
    return st.session_state.get("auth")


def is_teacher() -> bool:
    a = current_auth()
    return bool(a and a.get("role") == "teacher")


def is_student() -> bool:
    a = current_auth()
    return bool(a and a.get("role") == "student")


def login_teacher(email: str, password: str) -> bool:
    teacher = storage.authenticate_teacher(email, password)
    if not teacher:
        return False
    st.session_state["auth"] = {
        "role": "teacher",
        "email": teacher["email"],
        "name": teacher["name"],
    }
    return True


def login_student(session_code: str, student_id: str) -> str | None:
    """Returns error message string on failure, None on success."""
    cls = storage.get_class_by_code(session_code.strip().upper())
    if not cls:
        return "Session code not found. Check with your teacher."

    student = storage.get_student(cls["id"], student_id.strip())
    if not student:
        return "Your student ID is not on this class roster."

    st.session_state["auth"] = {
        "role": "student",
        "class_id": cls["id"],
        "session_code": cls["session_code"],
        "class_name": cls["name"],
        "student_id": student["student_id"],
        "display_name": student["display_name"],
    }
    return None


def logout() -> None:
    for k in ("auth", "orch", "agent", "session_id", "messages", "state", "theory"):
        st.session_state.pop(k, None)
