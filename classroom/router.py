"""Theory router.

Given the current learner state and the currently active theory, pick the
theory for the NEXT agent turn. Biased toward staying with the current
theory to prevent flip-flopping.
"""

from __future__ import annotations

import json

from providers import LLMProvider


ROUTER_SYSTEM = """\
You are a pedagogical router. Given a learner's current state, pick the
teaching theory best suited for the NEXT agent turn.

Output JSON ONLY with this exact shape:
{"theory": "<name>", "reason": "<short phrase, <=15 words>"}

Available theories (pick one by exact name):
{THEORIES}

Decision heuristics (in priority order):
1. If safety.distress_signals = true → keep current theory; reason:
   "distress - routing paused".
2. If the current theory is working (engagement >= neutral, frustration
   <= medium, turns_since_progress <= 2), KEEP IT. Bias strongly toward
   continuity.
3. If frustration = high OR help_seeking = gives_up OR
   turns_since_progress >= 3 → switch to a MORE SUPPORTIVE theory:
   prefer "scaffolding" or "direct_instruction" if available.
4. If confidence = overconfident AND mastery is emerging → switch to
   "socratic" if available (challenge assumptions).
5. If learner explicitly asked "just tell me" or similar → switch to
   "direct_instruction" if available.
6. Otherwise KEEP the current theory.

Only switch when heuristics 3-5 clearly apply. When in doubt, keep
current theory. Flip-flopping harms learning.
"""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


def route(
    state: dict,
    current_theory: str,
    available_theories: list[str],
    llm: LLMProvider,
) -> tuple[str, str]:
    """Return (chosen_theory, reason). Falls back to current on any error."""
    if current_theory not in available_theories:
        available_theories = list(dict.fromkeys([current_theory, *available_theories]))

    system = ROUTER_SYSTEM.replace("{THEORIES}", ", ".join(available_theories))
    user = (
        f"Current theory: {current_theory}\n\n"
        f"Learner state:\n{json.dumps(state, indent=2)}"
    )
    try:
        raw = llm.complete(system=system, user=user, max_tokens=120)
        decision = _parse_json(raw)
        theory = decision.get("theory", current_theory)
        reason = decision.get("reason", "")
        if theory not in available_theories:
            return current_theory, "invalid router output"
        return theory, reason[:100]
    except Exception:
        return current_theory, "router error - kept current"
