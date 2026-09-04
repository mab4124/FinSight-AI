"""
llm/base.py — Abstract LLMClient interface.

Why an abstraction?
    The application currently uses Gemma 3 4B via Ollama, but the
    rest of the codebase should not import Ollama-specific code.
    This decoupling means:
    - We can swap the runtime (Ollama → llama.cpp → cloud) in one place.
    - All tests can inject a MockLLMClient without starting a real model.
    - Interview question: "How would you change the LLM?" — easy answer.

Current implementation status:
    Phase 1: Abstract base class only.
    Phase 6: OllamaLLMClient will implement this.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Abstract base for all LLM clients.

    The application uses two generation modes:
    - generate(): free-form text generation (RAG answers, summaries).
    - generate_structured(): generation with a JSON schema constraint
      (structured financial metric extraction).
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> str:
        """Generate a text response from the model.

        Args:
            prompt: The user-facing prompt or assembled RAG context+question.
            system_prompt: Optional system-level instructions (grounding rules,
                           persona, safety instructions).
            max_tokens: Maximum tokens the model may generate.
            temperature: Sampling temperature.  Use 0.1 for factual/grounded
                         tasks; higher for creative/diverse outputs.

        Returns:
            The model's generated text response.

        Raises:
            LLMUnavailableError: If the model runtime is unreachable.
        """
        ...

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Generate a structured JSON response constrained by a schema.

        Used for financial metric extraction where we need validated,
        typed output rather than free-form text.

        Args:
            prompt: The extraction prompt.
            schema: JSON Schema dict describing the expected output structure.
            system_prompt: Optional system instructions.
            max_tokens: Maximum tokens to generate.

        Returns:
            Parsed and validated dict matching the provided schema.

        Raises:
            LLMUnavailableError: If the model runtime is unreachable.
            MalformedLLMResponseError: If the response cannot be parsed as JSON
                                       or does not match the schema.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the LLM runtime is reachable and ready.

        Used by the /health/llm endpoint and startup checks.
        """
        ...
