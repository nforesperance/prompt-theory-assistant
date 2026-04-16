"""Classroom Streamlit app.

Separate from `app.py` (the demo app). This one supports:
- Teacher login → class creation → roster upload (CSV/JSON) → dashboard.
- Student login via session code + student ID → tutoring chat seeded with
  their roster profile and per-turn state persistence.

Run:
    streamlit run app_classroom.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from providers import ENV_KEYS, PROVIDERS, get_provider

# ─── Bridge Streamlit secrets → environment variables ─────────────────────
# Streamlit Community Cloud injects API keys via st.secrets, not os.environ.
# Locally, providers.py already calls load_dotenv() so .env works unchanged.
for _env_var in ENV_KEYS.values():
    if _env_var not in os.environ:
        try:
            os.environ[_env_var] = st.secrets[_env_var]
        except (KeyError, FileNotFoundError):
            pass

from classroom import auth, roster, storage  # noqa: E402
from classroom.orchestrator import ClassroomOrchestrator  # noqa: E402

PROMPTS_DIR = Path("prompts")

st.set_page_config(page_title="Teaching Assistant — Classroom", page_icon="🎓", layout="wide")
storage.init_db()


# ─── Utilities ─────────────────────────────────────────────────────────────

def available_theories() -> list[str]:
    if not PROMPTS_DIR.exists():
        return []
    return sorted(
        p.name for p in PROMPTS_DIR.iterdir()
        if p.is_dir() and (p / "system_prompt.md").exists()
    )


def load_theory_prompt(theory: str) -> str:
    return (PROMPTS_DIR / theory / "system_prompt.md").read_text(encoding="utf-8")


def get_llm(provider_name: str, model: str | None = None):
    env_key = ENV_KEYS.get(provider_name)
    if env_key and not os.environ.get(env_key):
        st.error(
            f"Missing {env_key}. Set it in your `.env` (local) or in "
            f"**App settings → Secrets** (Streamlit Cloud) before chatting."
        )
        st.stop()
    return get_provider(provider_name, model)


# ─── Landing / role selection ──────────────────────────────────────────────

def render_landing():
    st.title("🎓 Teaching Assistant — Classroom")
    st.caption("Theory-grounded tutoring for classroom pilots.")

    tab_teacher, tab_student = st.tabs(["I'm a teacher", "I'm a student"])

    with tab_teacher:
        render_teacher_login()

    with tab_student:
        render_student_login()


def render_teacher_login():
    st.subheader("Teacher sign-in")
    with st.form("teacher_login"):
        email = st.text_input("School email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if auth.login_teacher(email, password):
            st.rerun()
        else:
            st.error("Invalid email or password.")

    with st.expander("Create teacher account (pilot signup)"):
        with st.form("teacher_signup"):
            s_email = st.text_input("Email", key="su_email")
            s_name = st.text_input("Full name", key="su_name")
            s_pw = st.text_input("Password (min 8 chars)", type="password", key="su_pw")
            s_submitted = st.form_submit_button("Create account")
        if s_submitted:
            if len(s_pw) < 8:
                st.error("Password must be at least 8 characters.")
            elif not s_email or not s_name:
                st.error("Email and name are required.")
            else:
                try:
                    storage.create_teacher(s_email, s_name, s_pw)
                    st.success("Account created. Please sign in above.")
                except Exception as e:
                    st.error(f"Could not create account: {e}")


def render_student_login():
    st.subheader("Student sign-in")
    st.caption("Ask your teacher for the session code.")
    with st.form("student_login"):
        code = st.text_input("Session code").upper()
        sid = st.text_input("Your student ID")
        submitted = st.form_submit_button("Join session")
    if submitted:
        err = auth.login_student(code, sid)
        if err:
            st.error(err)
        else:
            st.rerun()


# ─── Teacher dashboard ─────────────────────────────────────────────────────

def render_teacher():
    a = auth.current_auth()
    with st.sidebar:
        st.write(f"**{a['name']}**")
        st.caption(a["email"])
        if st.button("Sign out", width="stretch"):
            auth.logout()
            st.rerun()

    st.title("Teacher dashboard")

    tab_classes, tab_create = st.tabs(["My classes", "Create a class"])

    with tab_create:
        render_create_class(a["email"])

    with tab_classes:
        classes = storage.list_classes(a["email"])
        if not classes:
            st.info("You haven't created any classes yet.")
            return
        names = [f"{c['name']}  ·  code: {c['session_code']}" for c in classes]
        idx = st.selectbox("Select a class", range(len(classes)), format_func=lambda i: names[i])
        render_class_detail(classes[idx])


def render_create_class(teacher_email: str):
    theories = available_theories()
    if not theories:
        st.warning("No theory prompts found in `prompts/`. Generate one with `script.py`.")
        return

    providers = list(PROVIDERS)
    default_idx = providers.index("openai") if "openai" in providers else 0

    with st.form("create_class"):
        name = st.text_input("Class name (e.g. 'Math 7B')")
        topic = st.text_input("Topic for this session (e.g. 'Pythagorean theorem')")
        theory = st.selectbox("Starting teaching theory", theories)
        col_p, col_m = st.columns(2)
        with col_p:
            provider = st.selectbox("Model provider", providers, index=default_idx)
        with col_m:
            model = st.text_input(
                "Model (optional — blank uses provider default)",
                placeholder="e.g. gpt-4.1, claude-sonnet-4-5",
            )
        adaptive_routing = st.toggle(
            "Enable adaptive theory switching",
            value=True,
            help=(
                "When ON, the tutor may switch to a different pedagogical theory "
                "mid-session based on the learner's state (frustration, stuckness, "
                "etc.). When OFF, the tutor stays on the starting theory for the "
                "entire session."
            ),
        )
        st.caption(
            "Students will use whichever provider and model you pick here for their whole session."
        )
        submitted = st.form_submit_button("Create class")
    if submitted:
        if not name:
            st.error("Class name is required.")
            return
        env_key = ENV_KEYS.get(provider)
        if env_key and not os.environ.get(env_key):
            st.error(
                f"Cannot create class: {env_key} is not set. "
                "Add it to `.env` (local) or Streamlit Cloud secrets and retry."
            )
            return
        result = storage.create_class(
            teacher_email, name, topic, theory, provider,
            model.strip() or None, adaptive_routing,
        )
        st.success(f"Class created. Session code: **{result['session_code']}**")
        st.rerun()


def render_class_detail(cls: dict):
    st.markdown(f"### {cls['name']}")

    model_str = f"{cls['provider']} / {cls.get('model') or 'default'}"
    adaptive_str = "ON" if cls.get("adaptive_routing", 1) else "OFF"
    rows = [
        ("Session code", f"`{cls['session_code']}`"),
        ("Theory", cls["theory"]),
        ("Topic", cls["topic"] or "—"),
        ("Model", model_str),
        ("Adaptive routing", adaptive_str),
    ]
    for label, value in rows:
        lcol, vcol = st.columns([1, 4])
        lcol.caption(label)
        vcol.markdown(value)

    st.divider()

    sub_roster, sub_sessions = st.tabs(["Roster", "Student sessions"])

    with sub_roster:
        render_roster_upload(cls["id"])
        render_roster_table(cls["id"])

    with sub_sessions:
        render_sessions_list(cls["id"])


def render_roster_upload(class_id: int):
    st.markdown("#### Upload roster")
    st.caption(
        "CSV or JSON. Required columns: `student_id`, `display_name`. "
        "Optional: `grade_level`, `reading_level`, `language`, `accommodations`, `notes`."
    )
    uploaded = st.file_uploader("Roster file", type=["csv", "json"])
    if uploaded is not None:
        try:
            content = uploaded.read().decode("utf-8")
            students = roster.parse(content, uploaded.name)
        except roster.RosterError as e:
            st.error(f"Roster error: {e}")
            return
        if st.button(f"Replace roster with {len(students)} student(s)", type="primary"):
            storage.replace_roster(class_id, students)
            st.success(f"Roster updated: {len(students)} students.")
            st.rerun()


def render_roster_table(class_id: int):
    rows = storage.list_roster(class_id)
    if not rows:
        st.info("No students on the roster yet. Upload a file above.")
        return
    df = pd.DataFrame(rows).drop(columns=["class_id"])
    st.dataframe(df, width="stretch", hide_index=True)


def render_sessions_list(class_id: int):
    sessions = storage.list_sessions(class_id)
    if not sessions:
        st.info("No student sessions yet.")
        return
    df = pd.DataFrame(sessions)
    st.dataframe(df, width="stretch", hide_index=True)

    sid = st.number_input("Open session id", min_value=0, step=1, value=0)
    if sid:
        session = storage.get_session(int(sid))
        if not session or session["class_id"] != class_id:
            st.error("Session not found for this class.")
            return
        routing = session["state"].get("routing", {})
        history = routing.get("history", [])
        if history:
            st.markdown("**Theory timeline**")
            st.caption(f"Current: `{routing.get('current_theory') or '—'}`")
            st.dataframe(
                pd.DataFrame(history),
                width="stretch",
                hide_index=True,
            )

        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("**Transcript**")
            for m in session["transcript"]:
                with st.chat_message(m["role"]):
                    st.write(m["content"])
        with col2:
            st.markdown("**Learner state**")
            st.json(session["state"])


# ─── Student chat ──────────────────────────────────────────────────────────

def render_student():
    a = auth.current_auth()
    with st.sidebar:
        st.write(f"**{a['display_name']}**")
        st.caption(f"Class: {a['class_name']}")
        if st.button("Leave session", width="stretch"):
            auth.logout()
            st.rerun()

    cls = storage.get_class(a["class_id"])
    student = storage.get_student(a["class_id"], a["student_id"])

    # Initialize orchestrator once per session, using the provider/model
    # configured by the teacher for this class.
    if "orch" not in st.session_state:
        st.session_state["orch"] = ClassroomOrchestrator(
            llm=get_llm(cls["provider"], cls.get("model")),
            class_info=cls,
            student=student,
            prompt_loader=load_theory_prompt,
            theories_provider=available_theories,
        )
    orch: ClassroomOrchestrator = st.session_state["orch"]

    st.title(f"Hi {a['display_name'].split()[0]}! 👋")
    if cls.get("topic"):
        st.caption(f"Today's topic: **{cls['topic']}**")

    # Replay transcript
    for m in orch.messages:
        with st.chat_message(m["role"], avatar="🎓" if m["role"] == "assistant" else None):
            st.write(m["content"])

    user_msg = st.chat_input("Ask anything about today's topic…")
    if not user_msg:
        return

    # Safety pre-flight
    support = orch.check_safety(user_msg)
    if support:
        with st.chat_message("user"):
            st.write(user_msg)
        with st.chat_message("assistant", avatar="🎓"):
            st.warning(support)
        orch.record_support_turn(user_msg, support)
        return

    # Routing + system prompt refresh, then stream the reply
    orch.prepare_turn()
    with st.chat_message("user"):
        st.write(user_msg)
    with st.chat_message("assistant", avatar="🎓"):
        st.write_stream(orch.stream_reply(user_msg))


# ─── Router ────────────────────────────────────────────────────────────────

def main():
    if auth.is_teacher():
        render_teacher()
    elif auth.is_student():
        render_student()
    else:
        render_landing()


main()
