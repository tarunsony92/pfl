"""L5.5 enum extensions — TDD scaffold for dedupe + TVR work."""
from app.enums import ArtifactSubtype, VerificationLevelNumber


def test_dedupe_report_subtype_exists():
    assert ArtifactSubtype.DEDUPE_REPORT.value == "DEDUPE_REPORT"


def test_tvr_audio_subtype_exists():
    assert ArtifactSubtype.TVR_AUDIO.value == "TVR_AUDIO"


def test_l5_5_level_exists():
    assert VerificationLevelNumber.L5_5_DEDUPE_TVR.value == "L5_5_DEDUPE_TVR"


def test_l5_5_ordering_after_l5():
    members = list(VerificationLevelNumber)
    assert members.index(VerificationLevelNumber.L5_5_DEDUPE_TVR) == \
        members.index(VerificationLevelNumber.L5_SCORING) + 1
