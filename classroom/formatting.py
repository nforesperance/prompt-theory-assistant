"""Output formatting helpers.

Streamlit's markdown renderer understands KaTeX math only with:
    inline math:  $ ... $
    display math: $$ ... $$

LLMs frequently emit ChatGPT-style \\[ ... \\] / \\( ... \\) delimiters, or
strip the backslashes entirely leaving bare [ ... ] / ( ... ) that look
like prose. This module provides:

1. FORMATTING_INSTRUCTIONS — inject into the agent's system prompt so
   the model emits the right delimiters from the start.
2. fix_math() — best-effort repair for the cases where the model drifts.
"""

from __future__ import annotations

import re


FORMATTING_INSTRUCTIONS = """\
## OUTPUT FORMATTING

- Write replies in standard markdown.
- For ALL mathematical expressions, use LaTeX with these EXACT delimiters:
  - Inline math: enclose in single dollar signs, e.g. $a^2 + b^2 = c^2$
  - Display math (own line): enclose in double dollar signs, e.g.
    $$a = \\frac{v_f - v_i}{t}$$
- NEVER use \\[ \\], \\( \\), bare [ ], or bare ( ) for math — the
  rendering layer only understands $ and $$.
- For units inside math, use \\text{...} and a thin space \\,
  (e.g. $20\\,\\text{m/s}$, not "20,m/s").
- For variables defined in prose, still wrap them in inline math
  (e.g. write "the final velocity $v_f$", not "the final velocity (v_f)").
"""


# ─── Repair patterns ───────────────────────────────────────────────────────
# Ordered from most-specific to least-specific.

_LATEX_CMD = r"\\[a-zA-Z]+|\\frac|\\text|\\sqrt|_\{|\^\{|_[a-zA-Z0-9]|\^[a-zA-Z0-9]"


def _looks_like_math(s: str) -> bool:
    """Heuristic: does this substring contain LaTeX commands or math syntax?"""
    return bool(re.search(_LATEX_CMD, s)) or bool(re.search(r"[=+\-*/]\s*\\", s))


def _convert_bracketed(text: str, open_delim: str, close_delim: str, wrap: str) -> str:
    """Replace bracketed spans that look like math with $ or $$ wrappers."""
    pattern = re.compile(
        re.escape(open_delim) + r"\s*(.+?)\s*" + re.escape(close_delim),
        flags=re.DOTALL,
    )

    def sub(m: re.Match) -> str:
        inner = m.group(1)
        if _looks_like_math(inner):
            return f"{wrap}{inner}{wrap}"
        return m.group(0)

    return pattern.sub(sub, text)


def fix_math(text: str) -> str:
    """Best-effort: normalize malformed math delimiters to $ / $$."""
    if not text:
        return text

    # 1. Escaped LaTeX delimiters → dollar signs (always safe).
    text = re.sub(r"\\\[\s*(.+?)\s*\\\]", r"$$\1$$", text, flags=re.DOTALL)
    text = re.sub(r"\\\(\s*(.+?)\s*\\\)", r"$\1$", text, flags=re.DOTALL)

    # 2. Bare [ ... ] / ( ... ) containing LaTeX — only when clearly math.
    text = _convert_bracketed(text, "[", "]", "$$")
    text = _convert_bracketed(text, "(", ")", "$")

    # 3. "20,m/s" style — comma used where \, was intended. Only when
    # followed by a unit-like token inside existing math.
    text = re.sub(
        r"(\d),(\\text\{|[a-zA-Zμ°])",
        r"\1\\,\2",
        text,
    )

    return text
