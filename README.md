# Prompt Assist — Teaching Theory Corpus Analyzer

Reads PDF/TXT/MD documents from a corpus directory, identifies the underlying teaching/learning theory, and generates a production-ready system prompt (persona) that constrains an AI teaching agent's behaviour to that theory.

## Supported Theories

Automatically detected from corpus content:

- Constructivism (Piaget, Vygotsky)
- Scaffolding (Bruner, Wood)
- Direct Instruction (Rosenshine, Engelmann)
- Cognitive Apprenticeship (Collins, Brown, Newman)
- Self-Regulated Learning (Zimmerman, Pintrich)
- And others (Behaviourism, Connectivism, Socratic Method, Montessori, etc.)

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your key(s)
```

## Usage

```bash
# Using Claude (default)
python script.py data/corpus/constructivism

# Using OpenAI
python script.py data/corpus/scaffolding -p openai

# Override the model
python script.py data/corpus/direct_instruction -p claude -m claude-opus-4-20250514

# Custom output directory
python script.py data/corpus/self_regulated_learning -o output/srl/
```

### Arguments

| Argument | Description |
|---|---|
| `corpus_dir` | Path to directory containing PDF/TXT/MD documents (searched recursively) |
| `-p, --provider` | `claude` (default) or `openai` |
| `-m, --model` | Override the default model (`claude-sonnet-4-20250514` / `gpt-4.1`) |
| `-o, --output-dir` | Output directory (default: current directory) |

## Output

The script produces two files in the output directory:

1. **`system_prompt.md`** — The generated system prompt with persona, rules, interaction protocol, questioning framework, feedback protocol, scaffolding protocol, anti-patterns, and example conversational moves.
2. **`analysis.json`** — Structured theory classification with core principles, strategies, dos/don'ts, feedback rules, and key vocabulary.

## Example: Process All Theories

```bash
for dir in data/corpus/*/; do
    python script.py "$dir"
done
# Output lands in prompts/constructivism/, prompts/scaffolding/, etc.
```


# CLI mode
python agent.py prompts/constructivism/system_prompt.md

# Streamlit UI
streamlit run app.py
