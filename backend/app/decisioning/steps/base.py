"""Shared interface for all decisioning step modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.enums import StepStatus


@dataclass
class StepOutput:
    status: StepStatus
    step_name: str
    step_number: int
    model_used: str | None  # None for step 1 (pure python)
    output_data: dict[str, Any]
    citations: list[dict[str, Any]]  # [{artifact_id, locator, quoted_text}]
    hard_fail: bool = False  # short-circuits pipeline if True
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None
    # Usage tracking
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


class StepContext(Protocol):
    """What every step receives. Built by orchestrator."""

    case: Any  # Case ORM object
    artifacts: list[Any]  # CaseArtifact list
    extractions: dict[str, dict[str, Any]]  # extractor_name -> extraction data
    policy: dict[str, Any]  # from memory/policy.yaml
    heuristics: str  # from memory/heuristics.md
    prior_steps: dict[int, StepOutput]  # step_number -> output
