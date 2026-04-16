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
_BRIDGED_SECRETS = list(ENV_KEYS.values()) + [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_KEY",
    "DISABLE_TEACHER_SIGNUP",
]
for _env_var in _BRIDGED_SECRETS:
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


def teacher_signup_disabled() -> bool:
    """Hide the teacher self-signup form when this env/secret is truthy."""
    return os.environ.get("DISABLE_TEACHER_SIGNUP", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


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
    st.title("🎓 Assistant Pédagogique — Classe")
    st.caption("Tutorat fondé sur des théories pédagogiques pour les pilotes en classe.")

    tab_teacher, tab_student = st.tabs(["Je suis enseignant", "Je suis étudiant(e)"])

    with tab_teacher:
        render_teacher_login()

    with tab_student:
        render_student_login()


def render_teacher_login():
    st.subheader("Connexion enseignant")
    with st.form("teacher_login"):
        email = st.text_input("E-mail scolaire")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter")
    if submitted:
        if auth.login_teacher(email, password):
            st.rerun()
        else:
            st.error("E-mail ou mot de passe invalide.")

    if teacher_signup_disabled():
        return

    with st.expander("Créer un compte enseignant (inscription pilote)"):
        with st.form("teacher_signup"):
            s_email = st.text_input("E-mail", key="su_email")
            s_name = st.text_input("Nom complet", key="su_name")
            s_pw = st.text_input("Mot de passe (8 caractères min.)", type="password", key="su_pw")
            s_submitted = st.form_submit_button("Créer le compte")
        if s_submitted:
            if len(s_pw) < 8:
                st.error("Le mot de passe doit contenir au moins 8 caractères.")
            elif not s_email or not s_name:
                st.error("L'e-mail et le nom sont obligatoires.")
            else:
                try:
                    storage.create_teacher(s_email, s_name, s_pw)
                    st.success("Compte créé. Veuillez vous connecter ci-dessus.")
                except Exception as e:
                    st.error(f"Impossible de créer le compte : {e}")


def render_student_login():
    st.subheader("Connexion étudiant(e)")
    st.caption("Demandez le Tutor Id à votre enseignant.")
    with st.form("student_login"):
        code = st.text_input("Tutor Id").upper()
        sid = st.text_input("Votre identifiant étudiant(e)")
        submitted = st.form_submit_button("Rejoindre la session")
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
        # If the teacher signed up with their email in the Name field,
        # avoid rendering it twice — and avoid Streamlit auto-linking
        # the email when wrapped in markdown bold.
        display_name = a.get("name") or a["email"]
        st.markdown(f"**{display_name}**")
        if display_name.lower() != a["email"].lower():
            st.caption(a["email"])
        if st.button("Sign out", width="stretch"):
            auth.logout()
            st.rerun()

    st.title("Teacher dashboard")

    # Persistent success banner for class create/delete — rendered above
    # the view selector so it's visible regardless of which view is active.
    created = st.session_state.pop("class_created", None)
    if created:
        st.success(
            f"✅ Class **{created['name']}** created. "
            f"Tutor Id: **`{created['session_code']}`**"
        )

    # Programmatic view control — unlike st.tabs, this can be flipped
    # from code (e.g. after creating a class). Pending switches must be
    # applied *before* the widget is instantiated; Streamlit forbids
    # writing to a widget's session_state key after it renders.
    pending_view = st.session_state.pop("_pending_teacher_view", None)
    if pending_view is not None:
        st.session_state["teacher_view"] = pending_view

    st.segmented_control(
        "view",
        options=["My classes", "Create a class"],
        default="My classes",
        key="teacher_view",
        label_visibility="collapsed",
    )
    view = st.session_state.get("teacher_view") or "My classes"

    if view == "Create a class":
        render_create_class(a["email"])
    else:
        render_my_classes(a["email"])


def render_my_classes(teacher_email: str):
    classes = storage.list_classes(teacher_email)
    if not classes:
        st.info("You haven't created any classes yet. Use **Create a class** to start.")
        return

    # Pre-select a class if one was just created/opened from elsewhere.
    pending = st.session_state.pop("selected_class_id", None)
    default_idx = 0
    if pending is not None:
        for i, c in enumerate(classes):
            if c["id"] == pending:
                default_idx = i
                break

    names = [f"{c['name']}  ·  Tutor Id: {c['session_code']}" for c in classes]
    idx = st.selectbox(
        "Select a class",
        range(len(classes)),
        format_func=lambda i: names[i],
        index=default_idx,
        key="teacher_class_picker",
    )
    render_class_detail(classes[idx], teacher_email)


def render_create_class(teacher_email: str):
    theories = available_theories()
    if not theories:
        st.warning("No theory prompts found in `prompts/`. Generate one with `script.py`.")
        return

    providers = list(PROVIDERS)
    default_idx = providers.index("openai") if "openai" in providers else 0

    with st.form("create_class", clear_on_submit=True):
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
        st.toast(f"Class '{name}' created — Tutor Id {result['session_code']}", icon="✅")
        st.session_state["class_created"] = {
            "name": name,
            "session_code": result["session_code"],
        }
        st.session_state["_pending_teacher_view"] = "My classes"
        st.session_state["selected_class_id"] = result["id"]
        st.session_state.pop("teacher_class_picker", None)
        st.rerun()


def render_class_detail(cls: dict, teacher_email: str):
    header_col, delete_col = st.columns([4, 1])
    with header_col:
        st.markdown(f"### {cls['name']}")
    with delete_col:
        render_delete_class_button(cls, teacher_email)

    model_str = f"{cls['provider']} / {cls.get('model') or 'default'}"
    adaptive_str = "ON" if cls.get("adaptive_routing", 1) else "OFF"
    rows = [
        ("Tutor Id", f"`{cls['session_code']}`"),
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


def render_delete_class_button(cls: dict, teacher_email: str) -> None:
    """Destructive action with a two-step confirmation inside a popover."""
    with st.popover("🗑️ Delete class", use_container_width=True):
        st.warning(
            f"Permanently delete **{cls['name']}**, its roster, and all student sessions?\n\n"
            "This cannot be undone."
        )
        confirm_label = st.text_input(
            "Type the Tutor Id to confirm",
            key=f"del_confirm_{cls['id']}",
            placeholder=cls["session_code"],
        )
        if st.button(
            "Delete permanently",
            type="primary",
            key=f"del_btn_{cls['id']}",
            disabled=(confirm_label.strip().upper() != cls["session_code"]),
        ):
            deleted = storage.delete_class(cls["id"], teacher_email)
            if deleted:
                st.session_state.pop("teacher_class_picker", None)
                st.session_state.pop("selected_class_id", None)
                st.toast(f"Class '{cls['name']}' deleted", icon="🗑️")
                st.rerun()
            else:
                st.error("Could not delete — class not found or not owned by you.")


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

# Number of tutoring conditions each pilot participant completes. When a
# student has submitted this many evaluations, the final open-ended
# questionnaire is shown.
STUDY_REQUIRED_SESSIONS = 4


def render_student():
    a = auth.current_auth()

    # Study already fully completed — show a thank-you page on any future login.
    if storage.get_final_response(a["student_id"]):
        render_study_complete(a)
        return

    cls = storage.get_class(a["class_id"])
    student = storage.get_student(a["class_id"], a["student_id"])

    # Initialize orchestrator once per Streamlit session. Creates or resumes
    # the underlying DB session for this (class, student) pair.
    if "orch" not in st.session_state:
        st.session_state["orch"] = ClassroomOrchestrator(
            llm=get_llm(cls["provider"], cls.get("model")),
            class_info=cls,
            student=student,
            prompt_loader=load_theory_prompt,
            theories_provider=available_theories,
        )
    orch: ClassroomOrchestrator = st.session_state["orch"]

    existing_eval = storage.get_evaluation(orch.session_id)
    eval_count = storage.count_evaluations_for_student(a["student_id"])

    _render_student_sidebar(a, eval_count, eval_locked=existing_eval is not None)

    if existing_eval is not None:
        # This session has already been evaluated — chat is locked.
        if eval_count >= STUDY_REQUIRED_SESSIONS:
            render_final_questions(a)
        else:
            render_session_locked(a, existing_eval, eval_count)
        return

    if st.session_state.get("eval_pending"):
        render_evaluation_form(orch, cls, a)
        return

    render_chat(orch, cls, a)


def _render_student_sidebar(a: dict, eval_count: int, *, eval_locked: bool) -> None:
    with st.sidebar:
        st.write(f"**{a['display_name']}**")
        st.caption(f"Classe : {a['class_name']}")
        st.caption(f"Tutor Id : `{a['session_code']}`")
        st.caption(
            f"Progression : **{eval_count}/{STUDY_REQUIRED_SESSIONS}** "
            "sessions évaluées"
        )
        st.divider()
        if not eval_locked and not st.session_state.get("eval_pending"):
            if st.button(
                "Terminer la session et évaluer",
                width="stretch",
                type="primary",
            ):
                st.session_state["eval_pending"] = True
                st.rerun()
        if st.button("Quitter la session", width="stretch"):
            auth.logout()
            st.rerun()


def render_chat(orch: ClassroomOrchestrator, cls: dict, a: dict) -> None:
    st.title(f"Bonjour {a['display_name'].split()[0]} ! 👋")
    if cls.get("topic"):
        st.caption(f"Sujet du jour : **{cls['topic']}**")
    if orch.is_resumed:
        st.info(
            f"Bienvenue à nouveau — reprise de votre session précédente "
            f"({len(orch.messages) // 2} échange(s) jusqu'ici)."
        )

    for m in orch.messages:
        with st.chat_message(m["role"], avatar="🎓" if m["role"] == "assistant" else None):
            st.write(m["content"])

    user_msg = st.chat_input("Posez vos questions sur le sujet du jour…")
    if not user_msg:
        return

    support = orch.check_safety(user_msg)
    if support:
        with st.chat_message("user"):
            st.write(user_msg)
        with st.chat_message("assistant", avatar="🎓"):
            st.warning(support)
        orch.record_support_turn(user_msg, support)
        return

    orch.prepare_turn()
    with st.chat_message("user"):
        st.write(user_msg)
    with st.chat_message("assistant", avatar="🎓"):
        st.write_stream(orch.stream_reply(user_msg))


def render_evaluation_form(orch: ClassroomOrchestrator, cls: dict, a: dict) -> None:
    st.title("Évaluation de la session")
    st.caption(
        f"Tutor Id : `{a['session_code']}` · "
        f"Problème : {cls.get('topic') or '—'}"
    )
    st.caption(
        "1 = pas du tout d'accord · 4 = neutre · 7 = tout à fait d'accord"
    )

    with st.form("session_evaluation"):
        coherence = st.slider(
            "**Cohérence** — L'approche du tuteur était cohérente et "
            "il a tenu un style d'enseignement clair.",
            1, 7, 4,
        )
        made_me_think = st.slider(
            "**M'a fait réfléchir** — Le tuteur m'a aidé à raisonner "
            "sur le problème plutôt que de me donner la réponse.",
            1, 7, 4,
        )
        one_at_a_time = st.slider(
            "**Une chose à la fois** — Le tuteur posait une seule "
            "question à la fois plutôt que de me submerger.",
            1, 7, 4,
        )
        reuse = st.slider(
            "**Je l'utiliserais à nouveau** — J'utiliserais à nouveau "
            "ce tuteur pour un problème similaire.",
            1, 7, 4,
        )
        notes = st.text_area("Notes brèves (facultatif)", height=100)

        col_cancel, col_submit = st.columns([1, 2])
        with col_cancel:
            cancel = st.form_submit_button("Retour au chat", width="stretch")
        with col_submit:
            submit = st.form_submit_button(
                "Soumettre l'évaluation",
                type="primary",
                width="stretch",
            )

    if cancel:
        st.session_state.pop("eval_pending", None)
        st.rerun()
    if submit:
        try:
            storage.submit_evaluation(
                session_id=orch.session_id,
                class_id=a["class_id"],
                student_id=a["student_id"],
                ratings={
                    "coherence": coherence,
                    "made_me_think": made_me_think,
                    "one_at_a_time": one_at_a_time,
                    "reuse": reuse,
                },
                notes=notes.strip() or None,
            )
        except Exception as e:
            st.error(f"Impossible d'enregistrer l'évaluation : {e}")
            return
        st.session_state.pop("eval_pending", None)
        st.rerun()


def render_session_locked(a: dict, evaluation: dict, eval_count: int) -> None:
    remaining = STUDY_REQUIRED_SESSIONS - eval_count
    st.title("Évaluation enregistrée ✅")
    st.success(
        f"Merci! Vous avez évalué "
        f"**{eval_count}/{STUDY_REQUIRED_SESSIONS}** sessions."
    )
    if remaining > 0:
        st.info(
            f"Il vous reste **{remaining}** session(s) à compléter. "
            "Cliquez sur **Quitter la session** dans la barre latérale, "
            "puis connectez-vous au prochain tuteur avec le Tutor Id "
            "fourni sur votre carte de session."
        )
    with st.expander("Voir mes réponses pour cette session"):
        st.markdown(f"- **Cohérence** : {evaluation['coherence']}/7")
        st.markdown(f"- **M'a fait réfléchir** : {evaluation['made_me_think']}/7")
        st.markdown(f"- **Une chose à la fois** : {evaluation['one_at_a_time']}/7")
        st.markdown(f"- **Je l'utiliserais à nouveau** : {evaluation['reuse']}/7")
        if evaluation.get("notes"):
            st.markdown(f"- **Notes** : {evaluation['notes']}")


def render_final_questions(a: dict) -> None:
    st.title("Questions finales 🎯")
    st.caption("À remplir après vos quatre sessions (≈ 3 minutes).")
    st.info(
        "Vous avez terminé les quatre sessions de tutorat. "
        "Merci de répondre aux questions ci-dessous pour clôturer l'étude."
    )

    with st.form("final_questions"):
        differences = st.text_area(
            "Quelles différences avez-vous remarquées entre les quatre tuteurs ?",
            height=200,
        )
        standout = st.text_area(
            "Un tuteur particulièrement utile ou frustrant ? (facultatif)",
            height=150,
        )
        submit = st.form_submit_button(
            "Soumettre mes réponses", type="primary"
        )
    if submit:
        if not differences.strip():
            st.error("Merci de répondre à la première question.")
            return
        try:
            storage.submit_final_response(
                a["student_id"],
                differences.strip(),
                standout.strip() or None,
            )
        except Exception as e:
            st.error(f"Impossible d'enregistrer vos réponses : {e}")
            return
        st.rerun()


def render_study_complete(a: dict) -> None:
    with st.sidebar:
        st.write(f"**{a['display_name']}**")
        st.caption("Étude terminée")
        if st.button("Quitter", width="stretch"):
            auth.logout()
            st.rerun()
    st.title("Merci pour votre participation ! 🎉")
    st.success(
        "Vous avez terminé l'étude pilote. Toutes vos réponses ont été "
        "enregistrées."
    )
    st.caption(
        "Vous pouvez fermer cette page ou vous déconnecter via la barre "
        "latérale."
    )


# ─── Router ────────────────────────────────────────────────────────────────

def main():
    if auth.is_teacher():
        render_teacher()
    elif auth.is_student():
        render_student()
    else:
        render_landing()


main()
