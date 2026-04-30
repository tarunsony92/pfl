"""Classifier tests for L5.5 — DEDUPE_REPORT + TVR_AUDIO recognition."""
from app.enums import ArtifactSubtype
from app.worker.classifier import classify
from tests.fixtures.builders.dedupe_builder import build_dedupe_xlsx


def test_classify_dedupe_xlsx_by_filename_finpage_export():
    """Finpage export name like 'Customer_Dedupe (1).xlsx' matches via filename."""
    assert classify("Customer_Dedupe (1).xlsx") == ArtifactSubtype.DEDUPE_REPORT


def test_classify_dedupe_xlsx_by_filename_dedupe_keyword():
    """Any filename with 'dedupe' + xlsx wins."""
    assert classify("dedupe_2026.xlsx") == ArtifactSubtype.DEDUPE_REPORT


def test_classify_dedupe_xlsx_by_filename_duplicate_keyword():
    """The 'duplicate' synonym also wins."""
    assert classify("customer_duplicate_check.xlsx") == ArtifactSubtype.DEDUPE_REPORT


def test_classify_dedupe_xlsx_by_content_when_filename_neutral(tmp_path):
    """Filename without 'dedupe'/'duplicate' must classify via xlsx body."""
    body = build_dedupe_xlsx(tmp_path / "export.xlsx", customers=[]).read_bytes()
    assert classify("export_2026_04_24.xlsx", body_bytes=body) == ArtifactSubtype.DEDUPE_REPORT


def test_classify_tvr_audio_mp3():
    assert classify("f4dcb438.mp3") == ArtifactSubtype.TVR_AUDIO


def test_classify_tvr_audio_wav():
    assert classify("call_recording.wav") == ArtifactSubtype.TVR_AUDIO


def test_classify_tvr_audio_m4a():
    assert classify("tvr.m4a") == ArtifactSubtype.TVR_AUDIO


def test_dedupe_branch_precedes_auto_cam():
    """An ambiguous filename matching both dedupe and CAM patterns must
    pick DEDUPE_REPORT — the dedupe branch is checked first."""
    assert classify("auto_cam_dedupe.xlsx") == ArtifactSubtype.DEDUPE_REPORT


def test_legacy_cam_filename_still_classifies_as_auto_cam():
    """Regression: the AUTO_CAM filename branch must still fire for
    canonical CAM names that don't contain 'dedupe' or 'duplicate'."""
    assert classify("AUTO_CAM-10006079.xlsx") == ArtifactSubtype.AUTO_CAM
    assert classify("CAM_REPORT_10006079.xlsx") == ArtifactSubtype.AUTO_CAM
