"""Student state schema + per-turn update.

The state is a JSON blob that captures cognitive, affective, and behavioral
signals across a conversation. It is:
  - Injected into the agent's system prompt (so the agent adapts to the learner).
  - Used by the theory router (future work).
  - Persisted to SQLite per turn for teacher visibility.

Privacy: no PII beyond display_name. Fields here should be safe to surface
on a teacher dashboard.
"""

from __future__ import annotations

import json
from typing import Any

from providers import LLMProvider


def initial_state(student_profile: dict) -> dict:
    """Build a fresh state blob, seeding learner_profile from roster."""
    return {
        "session": {
            "current_topic": None,
            "current_goal": None,
            "turn_count": 0,
            "turns_since_progress": 0,
        },
        "cognitive": {
            "concept_mastery": {},
            "prior_knowledge_surfaced": [],
            "misconceptions": [],
        },
        "affect": {
            "engagement": "neutral",
            "confusion": "low",
            "frustration": "low",
            "confidence": "appropriate",
        },
        "behavior": {
            "help_seeking": "unknown",
            "preferred_pace": "unknown",
            "response_depth": "unknown",
        },
        "learner_profile": {
            "display_name": student_profile.get("display_name"),
            "grade_level": student_profile.get("grade_level"),
            "reading_level": student_profile.get("reading_level"),
            "language": student_profile.get("language", "en"),
            "accommodations": (
                student_profile.get("accommodations", "").split(";")
                if student_profile.get("accommodations") else []
            ),
        },
        "safety": {
            "distress_signals": False,
            "off_topic_drift": False,
        },
        "routing": {
            "current_theory": None,
            "history": [],
        },
    }


STATE_UPDATER_SYSTEM = """\
You track a learner's state across a tutoring conversation.

Given the previous state JSON and the latest exchange (learner message +
agent reply), output the UPDATED state JSON.

Rules:
- Output ONLY the JSON object, no markdown, no explanation.
- Be conservative: only change fields when the latest turn provides CLEAR
  evidence. When in doubt, keep the previous value.
- Increment session.turn_count by 1.
- Increment session.turns_since_progress unless the learner showed clear
  progress this turn (reset to 0 in that case).
- For concept_mastery: key = short concept name (snake_case). Value =
  {"level": float 0-1, "evidence": integer count}.
- affect values MUST use the allowed vocabulary:
    engagement: engaged | neutral | bored
    confusion: low | medium | high
    frustration: low | medium | high
    confidence: underconfident | appropriate | overconfident
- behavior values MUST use the allowed vocabulary:
    help_seeking: asks | guesses | gives_up | unknown
    preferred_pace: fast | step_by_step | exploratory | unknown
    response_depth: terse | moderate | verbose | unknown
- safety.distress_signals = true ONLY for expressions of hopelessness,
  self-harm, or sustained severe distress (not normal frustration).
- Do NOT modify learner_profile — it is set by the teacher.
- Do NOT modify routing — it is managed by the orchestrator, not you.
"""


def record_theory_change(
    state: dict,
    new_theory: str,
    reason: str,
) -> dict:
    """Append a routing event if the theory has changed.

    Called by the orchestrator (not the state updater LLM). Idempotent:
    a no-op when new_theory matches the current theory.
    """
    routing = state.setdefault("routing", {"current_theory": None, "history": []})
    if routing.get("current_theory") == new_theory:
        return state
    routing["history"].append({
        "turn": state["session"].get("turn_count", 0),
        "theory": new_theory,
        "reason": reason,
    })
    routing["current_theory"] = new_theory
    return state


SAFETY_SYSTEM = """\
You are a safety monitor for a classroom tutoring agent.

Analyze the learner's latest message ONLY. Output JSON:
{"distress": bool, "reason": "short phrase or empty string"}

Set distress=true ONLY for:
- Expressions of hopelessness ("I give up on everything", "I'm worthless")
- Self-harm or harm-to-others ideation
- Sustained severe emotional distress beyond academic frustration

Do NOT flag:
- Normal academic frustration ("this is hard", "I don't get it")
- Confusion or mistakes
- Mild disengagement

Output JSON only, no explanation.
"""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


def update_state(
    state: dict,
    user_msg: str,
    agent_msg: str,
    llm: LLMProvider,
) -> dict:
    """Run a cheap LLM call to update state based on the latest exchange."""
    prompt = (
        f"Previous state:\n{json.dumps(state, indent=2)}\n\n"
        f"Latest exchange:\n"
        f"Learner: {user_msg}\n"
        f"Agent: {agent_msg}"
    )
    try:
        raw = llm.complete(system=STATE_UPDATER_SYSTEM, user=prompt, max_tokens=800)
        updated = _parse_json(raw)
        # Preserve fields the LLM must not touch.
        updated["learner_profile"] = state["learner_profile"]
        updated["routing"] = state.get("routing", {"current_theory": None, "history": []})
        return updated
    except Exception:
        # Never block the conversation on state-update failure.
        state["session"]["turn_count"] += 1
        return state


def check_safety(user_msg: str, llm: LLMProvider) -> dict:
    """Pre-flight safety check on the learner's message."""
    try:
        raw = llm.complete(system=SAFETY_SYSTEM, user=user_msg, max_tokens=100)
        return _parse_json(raw)
    except Exception:
        return {"distress": False, "reason": ""}


def render_state_block(state: dict) -> str:
    """Format the state as a markdown block to inject into the system prompt."""
    profile = state["learner_profile"]
    affect = state["affect"]
    behavior = state["behavior"]
    cognitive = state["cognitive"]
    session = state["session"]

    accommodations = ", ".join(profile.get("accommodations") or []) or "none"

    return f"""\
## LEARNER CONTEXT

Name: {profile.get('display_name') or 'Learner'}
Grade level: {profile.get('grade_level') or 'unspecified'}
Reading level: {profile.get('reading_level') or 'unspecified'}
Language: {profile.get('language', 'en')}
Accommodations: {accommodations}

Current topic: {session.get('current_topic') or 'not yet established'}
Turns in conversation: {session.get('turn_count', 0)}

Affect signals: engagement={affect['engagement']}, confusion={affect['confusion']}, \
frustration={affect['frustration']}, confidence={affect['confidence']}

Behavior signals: help_seeking={behavior['help_seeking']}, pace={behavior['preferred_pace']}

Concepts mastered: {list(cognitive['concept_mastery'].keys()) or 'none yet'}
Known misconceptions: {cognitive['misconceptions'] or 'none observed'}

Adapt your vocabulary, pacing, and scaffolding to this learner. If \
accommodations include "simplified_language", use shorter sentences and \
concrete examples. If frustration is high, reduce cognitive load.
"""
