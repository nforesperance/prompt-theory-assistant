"""
Teaching Agent – Chat with an AI constrained by a pedagogical system prompt.

Usage (CLI):
    python agent.py prompts/constructivism/system_prompt.md
    python agent.py prompts/constructivism/system_prompt.md --provider openai
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from providers import get_provider, LLMProvider, PROVIDERS


class TeachingAgent:
    """Stateful chat agent that follows a pedagogical system prompt."""

    def __init__(self, system_prompt: str, provider: LLMProvider):
        self.system_prompt = system_prompt
        self.provider = provider
        self.messages: list[dict] = []

    def send(self, user_message: str) -> str:
        """Send a message and get a complete response."""
        self.messages.append({"role": "user", "content": user_message})
        reply = self.provider.chat(
            system=self.system_prompt,
            messages=self.messages,
        )
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def stream(self, user_message: str):
        """Send a message and yield response chunks (for streaming UI)."""
        self.messages.append({"role": "user", "content": user_message})
        full_reply = []
        for chunk in self.provider.chat_stream(
            system=self.system_prompt,
            messages=self.messages,
        ):
            full_reply.append(chunk)
            yield chunk
        self.messages.append({"role": "assistant", "content": "".join(full_reply)})

    def reset(self):
        """Clear conversation history."""
        self.messages = []


def run_cli(agent: TeachingAgent):
    """Interactive terminal chat loop."""
    print("=" * 60)
    print("  Teaching Agent  (type 'quit' to exit, 'reset' to restart)")
    print(f"  Provider: {agent.provider.model}")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("Goodbye!")
            break
        if user_input.lower() == "reset":
            agent.reset()
            print("[Conversation reset]\n")
            continue

        print("\nAgent: ", end="", flush=True)
        for chunk in agent.stream(user_input):
            print(chunk, end="", flush=True)
        print("\n")


def main():
    parser = argparse.ArgumentParser(description="Chat with a theory-constrained teaching agent.")
    parser.add_argument(
        "prompt_file",
        type=Path,
        help="Path to a system_prompt.md file.",
    )
    parser.add_argument(
        "-p", "--provider",
        choices=list(PROVIDERS),
        default="claude",
        help="LLM provider (default: claude).",
    )
    parser.add_argument("-m", "--model", default=None, help="Override the default model.")
    args = parser.parse_args()

    if not args.prompt_file.is_file():
        sys.exit(f"Error: {args.prompt_file} not found.")

    system_prompt = args.prompt_file.read_text(encoding="utf-8")
    provider = get_provider(args.provider, args.model)
    agent = TeachingAgent(system_prompt, provider)
    run_cli(agent)


if __name__ == "__main__":
    main()
