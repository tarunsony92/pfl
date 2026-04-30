"""Tests for BaseExtractor contract and ExtractionResult dataclass."""

import pytest

from app.enums import ExtractionStatus
from app.worker.extractors.base import BaseExtractor, ExtractionResult

# ---------------------------------------------------------------------------
# ExtractionResult dataclass
# ---------------------------------------------------------------------------


def test_extraction_result_defaults():
    result = ExtractionResult(
        status=ExtractionStatus.SUCCESS,
        schema_version="1.0",
        data={"foo": "bar"},
    )
    assert result.warnings == []
    assert result.error_message is None


def test_extraction_result_with_all_fields():
    result = ExtractionResult(
        status=ExtractionStatus.PARTIAL,
        schema_version="2.0",
        data={"x": 1},
        warnings=["w1", "w2"],
        error_message="some error",
    )
    assert result.status == ExtractionStatus.PARTIAL
    assert result.schema_version == "2.0"
    assert result.data == {"x": 1}
    assert result.warnings == ["w1", "w2"]
    assert result.error_message == "some error"


def test_extraction_result_warnings_are_independent():
    """Each instance gets its own warnings list (default_factory)."""
    r1 = ExtractionResult(ExtractionStatus.SUCCESS, "1.0", {})
    r2 = ExtractionResult(ExtractionStatus.SUCCESS, "1.0", {})
    r1.warnings.append("x")
    assert r2.warnings == []


# ---------------------------------------------------------------------------
# BaseExtractor contract
# ---------------------------------------------------------------------------


def test_base_extractor_is_abstract():
    """Instantiating BaseExtractor directly must raise TypeError."""
    with pytest.raises(TypeError):
        BaseExtractor()  # type: ignore[abstract]


def test_concrete_extractor_must_implement_extract():
    """A concrete subclass that omits extract() should still be abstract."""

    class IncompleteExtractor(BaseExtractor):
        pass

    with pytest.raises(TypeError):
        IncompleteExtractor()  # type: ignore[abstract]


async def test_concrete_extractor_can_be_instantiated_and_called():
    """A properly implemented subclass works end-to-end."""

    class EchoExtractor(BaseExtractor):
        extractor_name = "echo"
        schema_version = "1.0"

        async def extract(self, filename: str, body_bytes: bytes) -> ExtractionResult:
            return ExtractionResult(
                status=ExtractionStatus.SUCCESS,
                schema_version=type(self).schema_version,
                data={"filename": filename, "size": len(body_bytes)},
            )

    extractor = EchoExtractor()
    result = await extractor.extract("test.txt", b"hello")
    assert result.status == ExtractionStatus.SUCCESS
    assert result.data["filename"] == "test.txt"
    assert result.data["size"] == 5
    assert result.schema_version == "1.0"


def test_class_attributes_have_defaults():
    """extractor_name and schema_version class attrs exist on BaseExtractor."""
    assert BaseExtractor.extractor_name == ""
    assert BaseExtractor.schema_version == "1.0"
