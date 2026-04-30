"""Tests for address_normalizer — fuzzy match of messy Indian addresses."""

from __future__ import annotations

from app.verification.services.address_normalizer import (
    addresses_match,
    normalize_address,
    name_matches,
    name_is_related_via_father_husband,
)


def test_normalize_strips_punct_and_lowercases():
    raw = "H.NO. 123, Village Xyz, HISAR, HARYANA - 125001"
    norm = normalize_address(raw)
    assert norm == normalize_address(raw)  # idempotent
    assert "," not in norm
    assert "." not in norm
    assert norm.islower()


def test_normalize_expands_common_abbreviations():
    # Abbreviations ("h no", "vill", "teh", "dist") are dropped so they don't
    # dominate the token-set score.
    norm = normalize_address("H No 123, Vill Sadipur, Teh Hisar, Dist Hisar")
    assert "h no" not in norm
    assert "vill" not in norm
    assert "teh" not in norm
    assert "dist" not in norm
    assert "123" in norm
    assert "sadipur" in norm
    assert "hisar" in norm


def test_addresses_match_reorders_tokens():
    a = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    b = "Village Sadipur, 125001, Hisar, Haryana, 123"  # reordered
    assert addresses_match(a, b) is True


def test_addresses_match_tolerates_minor_typos():
    a = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    b = "H No 123 Village Sadipoor Hisar Haryana 125001"  # typo: sadipoor
    assert addresses_match(a, b) is True


def test_addresses_mismatch_when_different():
    a = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    b = "Flat 4B, MG Road, Bangalore, Karnataka 560001"
    assert addresses_match(a, b) is False


def test_addresses_match_handles_none_and_empty():
    assert addresses_match(None, "anything") is False
    assert addresses_match("something", "") is False
    assert addresses_match("", "") is False


def test_addresses_match_respects_custom_threshold():
    a = "H No 123, Village Sadipur, Hisar, Haryana 125001"
    # A completely unrelated address should never match, even at low threshold
    b = "Flat 9, MG Road, Jaipur"
    assert addresses_match(a, b, threshold=0.50) is False


def test_name_matches_case_insensitive_and_whitespace_tolerant():
    assert name_matches("AJAY SINGH", "Ajay Singh") is True
    assert name_matches("  ajay   singh  ", "Ajay Singh") is True
    assert name_matches("AJAY KUMAR SINGH", "AJAY SINGH") is False  # middle name differs


def test_name_is_related_via_father_husband_so_prefix():
    # Ration bill owner "RAM SINGH (S/O AJAY SINGH)" relates AJAY via father
    assert name_is_related_via_father_husband(
        owner_name="RAM SINGH",
        father_or_husband_name="AJAY SINGH",
        candidate="AJAY SINGH",
    ) is True


def test_name_is_related_via_father_husband_none_matches_false():
    assert name_is_related_via_father_husband(
        owner_name="RAM SINGH",
        father_or_husband_name=None,
        candidate="AJAY SINGH",
    ) is False
