from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.enums import ExtractionStatus


@dataclass
class ExtractionResult:
    status: ExtractionStatus
    schema_version: str
    data: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None


class BaseExtractor(ABC):
    """Abstract base for all document extractors.

    Signature rationale: ``(filename, body_bytes)`` is used so extractor unit
    tests don't have to construct ``CaseArtifact`` ORM objects.  The pipeline
    (T11) passes only the filename + bytes it already has in memory from
    unpacking.  This is consistent — all extractors use this signature.
    """

    extractor_name: str = ""
    schema_version: str = "1.0"

    @abstractmethod
    async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult: ...
