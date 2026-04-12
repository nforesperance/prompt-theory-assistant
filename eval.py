"""
Pedagogical Compliance Evaluator
=================================
Runs test scenarios against each teaching agent and uses an LLM judge
to score whether the agent's responses comply with the theory.

Usage:
    python eval.py                              # eval all theories, default provider
    python eval.py --theories constructivism    # eval one theory
    python eval.py --provider openai            # use openai for both agent + judge
    python eval.py --judge-provider claude      # use claude as judge, openai as agent

Output:
    - eval_results/report.json    : Full structured results
    - eval_results/summary.txt    : Human-readable summary
    - stdout                      : Live progress + summary table
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from providers import get_provider, LLMProvider, PROVIDERS
from agent import TeachingAgent
from test_scenarios import SCENARIOS

# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

JUDGE_SYSTEM = """\
You are an expert evaluator of AI teaching assistants. You assess whether
an agent's response complies with a specific pedagogical theory.

You will receive:
1. The teaching theory name.
2. A student message (the input to the agent).
3. The agent's response.
4. A list of expected behaviors (things the agent SHOULD do).
5. A list of anti-patterns (things the agent should NOT do).

Score each expected behavior as PASS or FAIL.
Score each anti-pattern as PASS (avoided) or FAIL (violated).

Then give an overall compliance score from 0-10 and a brief justification.

Respond ONLY with JSON (no markdown fences):
{
    "behavior_scores": [
        {"behavior": "...", "verdict": "PASS|FAIL", "evidence": "brief quote or note"}
    ],
    "antipattern_scores": [
        {"antipattern": "...", "verdict": "PASS|FAIL", "evidence": "brief quote or note"}
    ],
    "overall_score": 8,
    "justification": "brief overall assessment"
}
"""


def build_judge_prompt(
    theory: str,
    student_message: str,
    agent_response: str,
    should: list[str],
    should_not: list[str],
) -> str:
    return f"""## Theory: {theory}

## Student Message
{student_message}

## Agent Response
{agent_response}

## Expected Behaviors (should do)
{json.dumps(should, indent=2)}

## Anti-Patterns (should NOT do)
{json.dumps(should_not, indent=2)}
"""


def parse_judge_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Failed to parse judge response", "raw": raw}


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

def run_eval(
    theory: str,
    prompt_path: Path,
    agent_provider: LLMProvider,
    judge_provider: LLMProvider,
    scenarios: list[dict],
) -> dict:
    """Run all scenarios for a single theory and return results."""
    system_prompt = prompt_path.read_text(encoding="utf-8")
    agent = TeachingAgent(system_prompt, agent_provider)

    theory_results = {
        "theory": theory,
        "prompt_file": str(prompt_path),
        "agent_model": agent_provider.model,
        "judge_model": judge_provider.model,
        "scenarios": [],
        "summary": {},
    }

    total_score = 0
    total_behaviors_pass = 0
    total_behaviors = 0
    total_antipatterns_pass = 0
    total_antipatterns = 0

    for scenario in scenarios:
        sid = scenario["id"]
        expectations = scenario["expectations"].get(theory)
        if not expectations:
            continue

        print(f"    [{sid}] {scenario['description']}")

        # Get agent response (fresh conversation each time)
        agent.reset()
        agent_response = agent.send(scenario["student_message"])
        print(f"      Agent responded ({len(agent_response)} chars)")

        # Judge the response
        judge_input = build_judge_prompt(
            theory=theory,
            student_message=scenario["student_message"],
            agent_response=agent_response,
            should=expectations["should"],
            should_not=expectations["should_not"],
        )

        judge_raw = judge_provider.complete(
            system=JUDGE_SYSTEM,
            user=judge_input,
            max_tokens=2048,
        )
        judgment = parse_judge_response(judge_raw)

        # Tally scores
        scenario_result = {
            "id": sid,
            "description": scenario["description"],
            "student_message": scenario["student_message"],
            "agent_response": agent_response,
            "judgment": judgment,
        }

        if "error" not in judgment:
            score = judgment.get("overall_score", 0)
            total_score += score

            b_pass = sum(1 for b in judgment.get("behavior_scores", []) if b["verdict"] == "PASS")
            b_total = len(judgment.get("behavior_scores", []))
            a_pass = sum(1 for a in judgment.get("antipattern_scores", []) if a["verdict"] == "PASS")
            a_total = len(judgment.get("antipattern_scores", []))

            total_behaviors_pass += b_pass
            total_behaviors += b_total
            total_antipatterns_pass += a_pass
            total_antipatterns += a_total

            print(f"      Score: {score}/10 | Behaviors: {b_pass}/{b_total} | Anti-patterns avoided: {a_pass}/{a_total}")
        else:
            print(f"      [warn] Judge parse error")

        theory_results["scenarios"].append(scenario_result)

    n = len(theory_results["scenarios"])
    theory_results["summary"] = {
        "avg_score": round(total_score / n, 1) if n else 0,
        "behaviors_passed": total_behaviors_pass,
        "behaviors_total": total_behaviors,
        "antipatterns_avoided": total_antipatterns_pass,
        "antipatterns_total": total_antipatterns,
        "scenario_count": n,
    }

    return theory_results


# ---------------------------------------------------------------------------
# Discover prompts
# ---------------------------------------------------------------------------

def discover_prompts() -> dict[str, Path]:
    prompts = {}
    prompts_dir = Path("prompts")
    if prompts_dir.is_dir():
        for p in sorted(prompts_dir.rglob("system_prompt.md")):
            theory_name = p.parent.name
            prompts[theory_name] = p
    return prompts


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(all_results: list[dict]):
    print(f"\n{'='*72}")
    print(f"  EVALUATION SUMMARY")
    print(f"{'='*72}")
    print(f"  {'Theory':<25} {'Score':>7} {'Behaviors':>12} {'Anti-pat':>12}")
    print(f"  {'-'*25} {'-'*7} {'-'*12} {'-'*12}")

    for r in all_results:
        s = r["summary"]
        theory = r["theory"].replace("_", " ").title()
        score = f"{s['avg_score']}/10"
        behaviors = f"{s['behaviors_passed']}/{s['behaviors_total']}"
        anti = f"{s['antipatterns_avoided']}/{s['antipatterns_total']}"
        print(f"  {theory:<25} {score:>7} {behaviors:>12} {anti:>12}")

    print(f"{'='*72}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate teaching agents for pedagogical compliance.")
    parser.add_argument(
        "--theories", nargs="*", default=None,
        help="Theories to evaluate (default: all discovered prompts).",
    )
    parser.add_argument(
        "-p", "--provider", choices=list(PROVIDERS), default="openai",
        help="LLM provider for the agent (default: openai).",
    )
    parser.add_argument(
        "--judge-provider", choices=list(PROVIDERS), default=None,
        help="LLM provider for the judge (default: same as --provider).",
    )
    parser.add_argument("-m", "--model", default=None, help="Override agent model.")
    parser.add_argument("--judge-model", default=None, help="Override judge model.")
    parser.add_argument(
        "-o", "--output-dir", default="eval_results",
        help="Output directory (default: eval_results/).",
    )
    parser.add_argument(
        "--scenarios", nargs="*", default=None,
        help="Run only specific scenario IDs (default: all).",
    )
    args = parser.parse_args()

    # Discover prompts
    available = discover_prompts()
    if not available:
        sys.exit("No prompts found in prompts/. Run script.py first.")

    # Filter theories
    if args.theories:
        theories = {t: available[t] for t in args.theories if t in available}
        missing = [t for t in args.theories if t not in available]
        if missing:
            print(f"Warning: theories not found: {missing}")
            print(f"Available: {list(available.keys())}")
    else:
        theories = available

    if not theories:
        sys.exit("No matching theories to evaluate.")

    # Filter scenarios
    scenarios = SCENARIOS
    if args.scenarios:
        scenarios = [s for s in SCENARIOS if s["id"] in args.scenarios]
        if not scenarios:
            sys.exit(f"No matching scenarios. Available: {[s['id'] for s in SCENARIOS]}")

    # Init providers
    agent_provider = get_provider(args.provider, args.model)
    judge_name = args.judge_provider or args.provider
    judge_provider = get_provider(judge_name, args.judge_model)

    print(f"Agent: {args.provider} ({agent_provider.model})")
    print(f"Judge: {judge_name} ({judge_provider.model})")
    print(f"Theories: {list(theories.keys())}")
    print(f"Scenarios: {len(scenarios)}")
    print()

    # Run evals
    all_results = []
    for theory, prompt_path in theories.items():
        print(f"  [{theory.replace('_', ' ').title()}]")
        result = run_eval(theory, prompt_path, agent_provider, judge_provider, scenarios)
        all_results.append(result)
        print()

    # Print summary
    print_summary(all_results)

    # Save results
    os.makedirs(args.output_dir, exist_ok=True)

    report_path = os.path.join(args.output_dir, "report.json")
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "agent_provider": args.provider,
            "agent_model": agent_provider.model,
            "judge_provider": judge_name,
            "judge_model": judge_provider.model,
            "results": all_results,
        }, f, indent=2)
    print(f"\nFull report: {report_path}")

    # Human-readable summary
    summary_path = os.path.join(args.output_dir, "summary.txt")
    with open(summary_path, "w") as f:
        f.write(f"Evaluation — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Agent: {args.provider} ({agent_provider.model})\n")
        f.write(f"Judge: {judge_name} ({judge_provider.model})\n\n")
        for r in all_results:
            s = r["summary"]
            f.write(f"{r['theory'].replace('_', ' ').title()}\n")
            f.write(f"  Average score:       {s['avg_score']}/10\n")
            f.write(f"  Behaviors passed:    {s['behaviors_passed']}/{s['behaviors_total']}\n")
            f.write(f"  Anti-patterns avoided: {s['antipatterns_avoided']}/{s['antipatterns_total']}\n")
            f.write(f"\n")
            for sc in r["scenarios"]:
                j = sc["judgment"]
                if "error" not in j:
                    f.write(f"  [{sc['id']}] Score: {j['overall_score']}/10\n")
                    f.write(f"    {j['justification']}\n\n")
    print(f"Summary:     {summary_path}")


if __name__ == "__main__":
    main()
