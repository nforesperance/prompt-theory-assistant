"""
Shared LLM provider abstraction used by both script.py and agent.py.
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from typing import Generator

from dotenv import load_dotenv

load_dotenv()


class LLMProvider(ABC):
    """Base class – subclass per provider."""

    model: str

    @abstractmethod
    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str: ...

    @abstractmethod
    def chat(
        self,
        system: str,
        messages: list[dict],
        *,
        max_tokens: int = 2048,
    ) -> str:
        """Multi-turn chat completion."""
        ...

    @abstractmethod
    def chat_stream(
        self,
        system: str,
        messages: list[dict],
        *,
        max_tokens: int = 2048,
    ) -> Generator[str, None, None]:
        """Streaming multi-turn chat – yields text deltas."""
        ...


class ClaudeProvider(LLMProvider):
    """Anthropic Claude."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text

    def chat(self, system: str, messages: list[dict], *, max_tokens: int = 2048) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return resp.content[0].text

    def chat_stream(self, system: str, messages: list[dict], *, max_tokens: int = 2048):
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text


class OpenAIProvider(LLMProvider):
    """OpenAI GPT-4o / GPT-4.1."""

    def __init__(self, model: str = "gpt-4.1"):
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    def chat(self, system: str, messages: list[dict], *, max_tokens: int = 2048) -> str:
        msgs = [{"role": "system", "content": system}] + messages
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=msgs,
        )
        return resp.choices[0].message.content

    def chat_stream(self, system: str, messages: list[dict], *, max_tokens: int = 2048):
        msgs = [{"role": "system", "content": system}] + messages
        stream = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=msgs,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


PROVIDERS: dict[str, type[LLMProvider]] = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
}

ENV_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def get_provider(name: str, model: str | None = None) -> LLMProvider:
    """Instantiate the chosen provider, optionally overriding the model."""
    env_var = ENV_KEYS[name]
    if not os.environ.get(env_var):
        sys.exit(
            f"Error: {env_var} is not set.\n"
            f"Export it or add it to your .env file:  {env_var}=sk-..."
        )
    cls = PROVIDERS[name]
    return cls(model) if model else cls()
