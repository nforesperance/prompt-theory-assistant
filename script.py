#!/usr/bin/env python3
"""
Teaching Assistant System Prompt Builder
========================================
Reads a corpus of teaching theory documents (PDF, TXT, MD),
identifies the pedagogical framework, and generates a professional
system prompt that constrains an LLM agent's teaching behavior.

Usage:
    python build_teaching_prompt.py /path/to/corpus/directory
    python build_teaching_prompt.py /path/to/corpus/directory --provider openai
    python build_teaching_prompt.py /path/to/corpus/directory --provider claude

Environment variables:
    ANTHROPIC_API_KEY  – required when --provider claude (default)
    OPENAI_API_KEY     – required when --provider openai

Output:
    - system_prompt.md  : The generated system prompt
    - analysis.json     : Theory identification + extracted rules
"""

import sys
import os
import json
import glob
import argparse
import textwrap
from pathlib import Path

from providers import get_provider, LLMProvider, PROVIDERS

# ---------------------------------------------------------------------------
# 1. Document reading
# ---------------------------------------------------------------------------

def read_text_file(path: str) -> str:
    """Read .txt or .md files."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def read_pdf_file(path: str) -> str:
    """Extract text from a PDF using pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


READERS = {
    ".pdf": read_pdf_file,
    ".txt": read_text_file,
    ".md":  read_text_file,
}


def load_corpus(directory: str) -> list[dict]:
    """Walk *directory* and return a list of {filename, content} dicts."""
    docs = []
    for ext, reader in READERS.items():
        for path in sorted(glob.glob(os.path.join(directory, f"**/*{ext}"), recursive=True)):
            try:
                content = reader(path)
                if content.strip():
                    docs.append({
                        "filename": os.path.relpath(path, directory),
                        "content": content,
                    })
                    print(f"  ✓ {docs[-1]['filename']}  ({len(content):,} chars)")
            except Exception as e:
                print(f"  ✗ {path}: {e}")
    return docs


# ---------------------------------------------------------------------------
# 2. Chunking – split corpus into LLM-friendly batches
# ---------------------------------------------------------------------------

MAX_CHARS_PER_DOC = 20_000   # ~5k tokens – truncate oversized individual docs
MAX_CHARS_PER_CHUNK = 60_000  # ~15k tokens per chunk – safe for 30k TPM limits


def truncate_doc(content: str, limit: int = MAX_CHARS_PER_DOC) -> str:
    """Keep start + end of oversized documents."""
    if len(content) <= limit:
        return content
    half = limit // 2
    return content[:half] + "\n\n[... truncated middle ...]\n\n" + content[-half:]


def prepare_corpus_chunks(docs: list[dict]) -> list[str]:
    """Split docs into chunks that each fit within MAX_CHARS_PER_CHUNK."""
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for doc in docs:
        content = truncate_doc(doc["content"])
        segment = f"<document filename=\"{doc['filename']}\">\n{content}\n</document>\n\n"
        seg_len = len(segment)

        if current_len + seg_len > MAX_CHARS_PER_CHUNK and current_parts:
            chunks.append("".join(current_parts))
            current_parts = []
            current_len = 0

        current_parts.append(segment)
        current_len += seg_len

    if current_parts:
        chunks.append("".join(current_parts))

    return chunks


# ---------------------------------------------------------------------------
# 4. Step A – Identify teaching theory & extract rules
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM = textwrap.dedent("""\
    You are an expert in educational psychology and pedagogical theory.
    You will be given a corpus of documents about one or more teaching theories.

    Your job:
    1. Identify the primary teaching theory/theories (e.g. Constructivism,
       Scaffolding, Zone of Proximal Development, Inquiry-Based Learning,
       Bloom's Taxonomy, Socratic Method, Montessori, etc.)
    2. Extract every concrete RULE, PRINCIPLE, STRATEGY, and TECHNIQUE
       described in the documents that should govern how a teaching agent
       behaves in conversation.
    3. Identify any explicit DO's and DON'Ts for the teacher/tutor.
    4. Identify assessment and feedback strategies described.
    5. Note the recommended interaction patterns and conversational moves.

    Respond ONLY with a JSON object (no markdown fences) with this schema:
    {
        "primary_theory": "string",
        "secondary_theories": ["string"],
        "theory_summary": "2-3 sentence summary of the core philosophy",
        "core_principles": ["string – each a clear actionable principle"],
        "teaching_strategies": ["string – concrete strategies the agent should use"],
        "questioning_techniques": ["string – types of questions to ask"],
        "feedback_rules": ["string – how to give feedback"],
        "scaffolding_moves": ["string – specific scaffolding techniques"],
        "dos": ["string – things the agent MUST do"],
        "donts": ["string – things the agent must NEVER do"],
        "assessment_strategies": ["string – how to assess understanding"],
        "interaction_patterns": ["string – conversation flow patterns"],
        "key_vocabulary": ["string – theory-specific terms to use naturally"]
    }
""")


def _parse_json_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON from an LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


MERGE_SYSTEM = textwrap.dedent("""\
    You are an expert in educational psychology. You will receive multiple
    JSON analyses of document chunks from the same corpus. Merge them into
    a single consolidated analysis.

    Combine and deduplicate all list fields. Pick the primary_theory that
    appears most consistently. Write a unified theory_summary.

    Respond ONLY with a single JSON object (no markdown fences) using the
    same schema as the inputs.
""")


def analyze_corpus(chunks: list[str], llm: LLMProvider) -> dict:
    """Analyse corpus in chunks, then merge if needed."""
    print("\n🔍 Analyzing teaching theory...")

    if len(chunks) == 1:
        print(f"   Processing 1 chunk ({len(chunks[0]):,} chars) ...")
        raw = llm.complete(
            system=ANALYSIS_SYSTEM,
            user=f"Here is the corpus of teaching documents:\n\n{chunks[0]}",
            max_tokens=4096,
        )
        return _parse_json_response(raw)

    # Multiple chunks – analyse each, then merge
    partial_analyses: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        print(f"   Processing chunk {i}/{len(chunks)} ({len(chunk):,} chars) ...")
        raw = llm.complete(
            system=ANALYSIS_SYSTEM,
            user=f"Here is batch {i} of {len(chunks)} from the corpus:\n\n{chunk}",
            max_tokens=4096,
        )
        partial_analyses.append(_parse_json_response(raw))

    print("   Merging chunk analyses ...")
    merge_input = json.dumps(partial_analyses, indent=2)
    raw = llm.complete(
        system=MERGE_SYSTEM,
        user=f"Merge these {len(partial_analyses)} partial analyses:\n\n{merge_input}",
        max_tokens=4096,
    )
    return _parse_json_response(raw)


# ---------------------------------------------------------------------------
# 5. Step B – Generate the system prompt
# ---------------------------------------------------------------------------

PROMPT_BUILDER_SYSTEM = textwrap.dedent("""\
    You are a world-class AI prompt engineer specializing in educational agents.

    You will receive a structured analysis of a teaching theory extracted from
    a corpus of pedagogical documents. Your task is to produce a COMPLETE,
    PRODUCTION-READY system prompt for an AI teaching assistant that strictly
    follows this theory.

    The system prompt you write must:
    1. Open with a clear PERSONA definition (who the agent is, its philosophy).
    2. State the pedagogical framework explicitly so the agent understands WHY
       it behaves the way it does.
    3. Include a RULES section with numbered, unambiguous behavioral rules
       derived from the theory. These must be concrete enough that compliance
       can be checked.
    4. Define the INTERACTION PROTOCOL – the step-by-step flow the agent must
       follow in every teaching interaction (e.g. assess → activate prior
       knowledge → guide → check → remediate).
    5. Include a QUESTIONING FRAMEWORK with example question stems.
    6. Include a FEEDBACK PROTOCOL with rules for how to respond to correct,
       partially correct, and incorrect answers.
    7. Include a SCAFFOLDING PROTOCOL with escalation levels (hint → leading
       question → partial reveal → direct instruction) and when to move
       between levels.
    8. Include ANTI-PATTERNS – things the agent must never do, with brief
       rationale tied to the theory.
    9. Include EXAMPLE CONVERSATIONAL MOVES – short model exchanges that
       illustrate the desired behavior.
    10. End with a META-COGNITION section instructing the agent to reflect
        on whether its responses align with the theory.

    Write the prompt in a clear, structured format using markdown headers.
    It should be self-contained – an LLM reading only this prompt should
    fully understand how to behave.

    Do NOT include any preamble or explanation. Output ONLY the system prompt.
""")


def build_system_prompt(analysis: dict, llm: LLMProvider) -> str:
    """Use the extracted analysis to generate a full system prompt."""
    print("🛠️  Building system prompt...")
    return llm.complete(
        system=PROMPT_BUILDER_SYSTEM,
        user=f"Here is the theory analysis to base the system prompt on:\n\n{json.dumps(analysis, indent=2)}",
        max_tokens=4096,
    )


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build a teaching-agent system prompt from a corpus of pedagogy documents."
    )
    parser.add_argument("corpus_dir", help="Directory containing PDF/TXT/MD files about a teaching theory")
    parser.add_argument("-o", "--output-dir", default=None, help="Where to write output files (default: prompts/<theory_name>/)")
    parser.add_argument(
        "-p", "--provider", choices=list(PROVIDERS.keys()), default="claude",
        help="LLM provider: 'claude' (default) or 'openai'"
    )
    parser.add_argument(
        "-m", "--model", default=None,
        help="Override the default model (claude: claude-sonnet-4-20250514, openai: gpt-4.1)"
    )
    args = parser.parse_args()

    corpus_dir = args.corpus_dir

    if not os.path.isdir(corpus_dir):
        print(f"Error: '{corpus_dir}' is not a directory.")
        sys.exit(1)

    # --- Init LLM provider ---
    llm = get_provider(args.provider, args.model)
    print(f"🤖 Using provider: {args.provider} ({llm.model})")

    # --- Load documents ---
    print(f"\n📂 Loading documents from: {corpus_dir}")
    docs = load_corpus(corpus_dir)
    if not docs:
        print("No readable documents found (.pdf, .txt, .md)")
        sys.exit(1)
    print(f"\n   Loaded {len(docs)} document(s)")

    # --- Prepare corpus chunks ---
    chunks = prepare_corpus_chunks(docs)
    total_chars = sum(len(c) for c in chunks)
    print(f"   Total corpus size: {total_chars:,} chars (~{total_chars // 4:,} tokens)")
    print(f"   Split into {len(chunks)} chunk(s)")

    # --- Step A: Analyze ---
    analysis = analyze_corpus(chunks, llm)
    print(f"   Identified theory: {analysis['primary_theory']}")
    if analysis.get("secondary_theories"):
        print(f"   Secondary: {', '.join(analysis['secondary_theories'])}")

    # --- Resolve output directory (use theory name if not specified) ---
    if args.output_dir:
        output_dir = args.output_dir
    else:
        theory_slug = analysis["primary_theory"].lower().replace(" ", "_").replace("-", "_")
        output_dir = os.path.join("prompts", theory_slug)
    os.makedirs(output_dir, exist_ok=True)

    analysis_path = os.path.join(output_dir, "analysis.json")
    with open(analysis_path, "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"   💾 Saved analysis → {analysis_path}")

    # --- Step B: Build prompt ---
    system_prompt = build_system_prompt(analysis, llm)

    prompt_path = os.path.join(output_dir, "system_prompt.md")
    with open(prompt_path, "w") as f:
        f.write(system_prompt)
    print(f"   💾 Saved system prompt → {prompt_path}")

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"  Provider: {args.provider} ({llm.model})")
    print(f"  Theory:   {analysis['primary_theory']}")
    print(f"  Rules:    {len(analysis.get('core_principles', []))} core principles")
    print(f"            {len(analysis.get('dos', []))} do's, {len(analysis.get('donts', []))} don'ts")
    print(f"  Prompt:   {len(system_prompt):,} chars")
    print(f"  Output:   {output_dir}/")
    print(f"{'='*60}")
    print(f"\n✅ Done! Use {prompt_path} as your agent's system prompt.")


if __name__ == "__main__":
    main()