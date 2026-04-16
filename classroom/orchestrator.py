"""Classroom turn orchestrator.

Encapsulates the per-turn pipeline so the Streamlit view stays focused
on UI concerns:

    safety check → theory routing → system-prompt refresh →
    agent stream → state update → persist

The orchestrator owns the agent, the learner state, the conversation
transcript, and the session id. The caller (Streamlit) is responsible
for rendering; it never touches state directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Generator

from agent import TeachingAgent
from classroom import storage
from classroom.formatting import FORMATTING_INSTRUCTIONS, fix_math
from classroom.router import route as route_theory
from classroom.state import (
    check_safety,
    initial_state,
    record_theory_change,
    render_state_block,
    update_state,
)
from providers import LLMProvider


SUPPORT_MESSAGE = (
    "I hear that you're going through something difficult. Your wellbeing "
    "matters more than any lesson right now. Please reach out to a trusted "
    "adult — a teacher, school counselor, or family member — so you don't "
    "have to handle this alone."
)

PromptLoader = Callable[[str], str]
TheoriesProvider = Callable[[], list[str]]


class ClassroomOrchestrator:
    """One instance per student session. Holds all mutable session state."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        class_info: dict,
        student: dict,
        prompt_loader: PromptLoader,
        theories_provider: TheoriesProvider,
        route_after_turn: int = 2,
    ):
        self._llm = llm
        self._class = class_info
        self._student = student
        self._load_prompt = prompt_loader
        self._list_theories = theories_provider
        self._route_after_turn = route_after_turn

        self.theory: str = class_info["theory"]
        self.state: dict = self._build_initial_state()
        self.messages: list[dict] = []
        self.session_id: int = storage.start_session(
            class_info["id"], student["student_id"], self.state
        )

        self.agent = TeachingAgent(self._compose_system_prompt(), llm)

    # ─── Public API ──────────────────────────────────────────────────────

    def check_safety(self, user_msg: str) -> str | None:
        """Return a support message if distress is detected, else None."""
        result = check_safety(user_msg, self._llm)
        if result.get("distress"):
            self.state["safety"]["distress_signals"] = True
            return SUPPORT_MESSAGE
        return None

    def record_support_turn(self, user_msg: str, support_msg: str) -> None:
        """Persist a safety-halted exchange without invoking the agent."""
        self.messages.append({"role": "user", "content": user_msg})
        self.messages.append({"role": "assistant", "content": support_msg})
        self._persist()

    def prepare_turn(self) -> None:
        """Route theory (if warranted) and refresh the agent's system prompt.

        Call once before streaming a reply. Routing is skipped entirely
        when the teacher disabled it for this class.
        """
        adaptive = bool(self._class.get("adaptive_routing", 1))
        if adaptive and self.state["session"]["turn_count"] >= self._route_after_turn:
            new_theory, reason = route_theory(
                self.state, self.theory, self._list_theories(), self._llm
            )
            if new_theory != self.theory:
                self.theory = new_theory
                self.state = record_theory_change(self.state, new_theory, reason)

        self.agent.system_prompt = self._compose_system_prompt()

    def stream_reply(self, user_msg: str) -> Generator[str, None, None]:
        """Stream the agent's reply; finalize state & persist when done.

        Chunks are yielded raw for live streaming; the fully-assembled
        reply is passed through `fix_math` before being stored so the
        transcript replay (and the teacher dashboard) always render
        correctly even when the model drifts from the math delimiters
        specified in the system prompt.
        """
        chunks: list[str] = []
        for chunk in self.agent.stream(user_msg):
            chunks.append(chunk)
            yield chunk
        reply = fix_math("".join(chunks))

        # Keep agent history consistent with what we stored.
        if self.agent.messages and self.agent.messages[-1]["role"] == "assistant":
            self.agent.messages[-1]["content"] = reply

        self.messages.append({"role": "user", "content": user_msg})
        self.messages.append({"role": "assistant", "content": reply})

        self.state = update_state(self.state, user_msg, reply, self._llm)
        self._persist()

    # ─── Internals ───────────────────────────────────────────────────────

    def _build_initial_state(self) -> dict:
        s = initial_state(self._student)
        if self._class.get("topic"):
            s["session"]["current_topic"] = self._class["topic"]
        s["routing"]["current_theory"] = self.theory
        s["routing"]["history"].append(
            {"turn": 0, "theory": self.theory, "reason": "session start"}
        )
        return s

    def _compose_system_prompt(self) -> str:
        return (
            self._load_prompt(self.theory)
            + "\n\n"
            + render_state_block(self.state)
            + "\n\n"
            + FORMATTING_INSTRUCTIONS
        )

    def _persist(self) -> None:
        storage.update_session(self.session_id, self.state, self.messages)
