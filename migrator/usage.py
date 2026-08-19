"""LLM usage accounting for the migration workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _usage_mapping(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        for key in ("usage_metadata", "usage", "token_usage"):
            value = response.get(key)
            if isinstance(value, dict):
                return value
        metadata = response.get("response_metadata")
        if isinstance(metadata, dict):
            return _usage_mapping(metadata)
        raw = response.get("raw")
        if raw is not None:
            return _usage_mapping(raw)
    for attribute in ("usage_metadata", "usage"):
        value = getattr(response, attribute, None)
        if isinstance(value, dict):
            return value
    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        return _usage_mapping(metadata)
    return {}


def extract_token_usage(response: Any) -> tuple[int, int, int]:
    """Extract prompt, completion, and total tokens from common LangChain shapes."""
    usage = _usage_mapping(response)
    prompt = _number(usage.get("prompt_tokens", usage.get("input_tokens")))
    completion = _number(usage.get("completion_tokens", usage.get("output_tokens")))
    total = _number(usage.get("total_tokens")) or prompt + completion
    return prompt, completion, total


def _model_name(response: Any, fallback: str) -> str:
    if isinstance(response, dict):
        metadata = response.get("response_metadata") or response.get("raw")
        if isinstance(metadata, dict):
            return str(metadata.get("model_name") or metadata.get("model") or fallback)
    metadata = getattr(response, "response_metadata", {})
    if isinstance(metadata, dict):
        return str(metadata.get("model_name") or metadata.get("model") or fallback)
    return fallback


@dataclass
class UsageRecord:
    stage: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float | None
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class UsageLedger:
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    records: list[UsageRecord] = field(default_factory=list)

    @classmethod
    def from_environment(cls) -> "UsageLedger":
        def rate(name: str) -> float | None:
            value = os.getenv(name, "").strip()
            if not value:
                return None
            try:
                parsed = float(value)
            except ValueError:
                return None
            return parsed if parsed >= 0 else None

        return cls(rate("AZURE_INPUT_COST_PER_1M_TOKENS"), rate("AZURE_OUTPUT_COST_PER_1M_TOKENS"))

    def record(self, response: Any, stage: str, fallback_model: str = "azure-structured-output") -> UsageRecord:
        prompt, completion, total = extract_token_usage(response)
        cost = None
        if self.input_cost_per_million is not None and self.output_cost_per_million is not None:
            cost = (
                prompt * self.input_cost_per_million
                + completion * self.output_cost_per_million
            ) / 1_000_000
        entry = UsageRecord(
            stage=stage,
            model=_model_name(response, fallback_model),
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            estimated_cost=cost,
        )
        self.records.append(entry)
        return entry

    @property
    def prompt_tokens(self) -> int:
        return sum(item.prompt_tokens for item in self.records)

    @property
    def completion_tokens(self) -> int:
        return sum(item.completion_tokens for item in self.records)

    @property
    def total_tokens(self) -> int:
        return sum(item.total_tokens for item in self.records)

    @property
    def estimated_cost(self) -> float | None:
        if any(item.estimated_cost is None for item in self.records):
            return None
        return sum(item.estimated_cost or 0 for item in self.records)

    def compact_summary(self) -> str:
        tokens = self.total_tokens
        if tokens >= 1_000_000:
            token_text = f"{tokens / 1_000_000:.1f}m"
        elif tokens >= 1_000:
            token_text = f"{tokens / 1_000:.1f}k"
        else:
            token_text = str(tokens)
        if self.estimated_cost is None:
            return f"{token_text} tokens · cost unavailable"
        return f"{token_text} tokens · est. ${self.estimated_cost:.2f}"
