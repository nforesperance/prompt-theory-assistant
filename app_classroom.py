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

from agent import TeachingAgent  # noqa: E402
from classroom import auth, roster, state, storage  # noqa: E402
from classroom.router import route as route_theory  # noqa: E402
from classroom.state import (  # noqa: E402
    check_safety,
    initial_state,
    record_theory_change,
    render_state_block,
    update_state,
)

PROMPTS_DIR = Path("prompts")
SUPPORT_MESSAGE = (
    "I hear that you're going through something difficult. Your wellbeing "
    "matters more than any lesson right now. Please reach out to a trusted "
    "adult — a teacher, school counselor, or family member — so you don't "
    "have to handle this alone."
)

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


def get_llm():
    provider_name = st.session_state.get("provider", "openai")
    model = st.session_state.get("model") or None
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

    with st.form("create_class"):
        name = st.text_input("Class name (e.g. 'Math 7B')")
        topic = st.text_input("Topic for this session (e.g. 'Pythagorean theorem')")
        theory = st.selectbox("Teaching theory", theories)
        submitted = st.form_submit_button("Create class")
    if submitted:
        if not name:
            st.error("Class name is required.")
            return
        result = storage.create_class(teacher_email, name, topic, theory)
        st.success(f"Class created. Session code: **{result['session_code']}**")
        st.rerun()


def render_class_detail(cls: dict):
    st.markdown(f"### {cls['name']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Session code", cls["session_code"])
    c2.metric("Theory", cls["theory"])
    c3.metric("Topic", cls["topic"] or "—")

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

    # Initialize session on first load
    if "session_id" not in st.session_state:
        s_state = initial_state(student)
        if cls.get("topic"):
            s_state["session"]["current_topic"] = cls["topic"]
        s_state["routing"]["current_theory"] = cls["theory"]
        s_state["routing"]["history"].append({
            "turn": 0,
            "theory": cls["theory"],
            "reason": "session start",
        })
        st.session_state["state"] = s_state
        st.session_state["messages"] = []
        st.session_state["theory"] = cls["theory"]
        st.session_state["session_id"] = storage.start_session(
            a["class_id"], a["student_id"], s_state
        )
        llm = get_llm()
        prompt = load_theory_prompt(cls["theory"]) + "\n\n" + render_state_block(s_state)
        st.session_state["agent"] = TeachingAgent(prompt, llm)

    st.title(f"Hi {a['display_name'].split()[0]}! 👋")
    if cls.get("topic"):
        st.caption(f"Today's topic: **{cls['topic']}**")

    # Replay transcript
    for m in st.session_state["messages"]:
        with st.chat_message(m["role"], avatar="🎓" if m["role"] == "assistant" else None):
            st.write(m["content"])

    user_msg = st.chat_input("Ask anything about today's topic…")
    if not user_msg:
        return

    llm = get_llm()

    # Safety pre-flight
    safety = check_safety(user_msg, llm)
    if safety.get("distress"):
        st.session_state["state"]["safety"]["distress_signals"] = True
        with st.chat_message("user"):
            st.write(user_msg)
        with st.chat_message("assistant", avatar="🎓"):
            st.warning(SUPPORT_MESSAGE)
        st.session_state["messages"].append({"role": "user", "content": user_msg})
        st.session_state["messages"].append({"role": "assistant", "content": SUPPORT_MESSAGE})
        storage.update_session(
            st.session_state["session_id"],
            st.session_state["state"],
            st.session_state["messages"],
        )
        return

    # Theory routing — runs only after we have signal (turn >= 2)
    agent: TeachingAgent = st.session_state["agent"]
    if st.session_state["state"]["session"]["turn_count"] >= 2:
        new_theory, reason = route_theory(
            st.session_state["state"],
            st.session_state["theory"],
            available_theories(),
            llm,
        )
        if new_theory != st.session_state["theory"]:
            st.session_state["theory"] = new_theory
            st.session_state["state"] = record_theory_change(
                st.session_state["state"], new_theory, reason
            )

    # Refresh system prompt with current state block each turn
    agent.system_prompt = (
        load_theory_prompt(st.session_state["theory"])
        + "\n\n"
        + render_state_block(st.session_state["state"])
    )

    with st.chat_message("user"):
        st.write(user_msg)

    with st.chat_message("assistant", avatar="🎓"):
        reply = st.write_stream(agent.stream(user_msg))

    st.session_state["messages"].append({"role": "user", "content": user_msg})
    st.session_state["messages"].append({"role": "assistant", "content": reply})

    # State update (best-effort, non-blocking on error)
    st.session_state["state"] = update_state(
        st.session_state["state"], user_msg, reply, llm
    )
    storage.update_session(
        st.session_state["session_id"],
        st.session_state["state"],
        st.session_state["messages"],
    )


# ─── Shared sidebar (provider selection) ───────────────────────────────────

def render_provider_sidebar():
    with st.sidebar:
        st.divider()
        st.markdown("**Model**")
        providers = list(PROVIDERS)
        default_idx = providers.index("openai") if "openai" in providers else 0
        st.session_state["provider"] = st.selectbox(
            "Provider", providers, index=default_idx, key="provider_select"
        )
        st.session_state["model"] = st.text_input(
            "Model override (optional)", value="", key="model_input",
            placeholder="e.g. gpt-4.1 or claude-sonnet-4-5",
        )
        env_key = ENV_KEYS.get(st.session_state["provider"])
        if env_key and not os.environ.get(env_key):
            st.warning(f"⚠️ {env_key} not set")


# ─── Router ────────────────────────────────────────────────────────────────

def main():
    if auth.is_teacher():
        render_provider_sidebar()
        render_teacher()
    elif auth.is_student():
        render_provider_sidebar()
        render_student()
    else:
        render_landing()


main()
