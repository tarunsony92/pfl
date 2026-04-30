"""Address + name normalisation and fuzzy match, tuned for rural Indian address text.

Used by Level 1 to cross-check addresses pulled from Aadhaar, Equifax, bank
statement, Google-Maps reverse-geocode, and ration/electricity bills — all of
which spell the same address slightly differently. Also used for the
owner-name / father-or-husband relationship rule on the ration/electricity bill.

Relies on ``rapidfuzz`` (already a backend dep) for token-set-based scoring,
which is robust to word reordering + minor typos while staying insensitive to
useless abbreviations like ``H No``, ``Vill``, ``Teh``, ``Dist``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from rapidfuzz.fuzz import partial_ratio, token_set_ratio


# Abbreviations / noise words we strip before comparison. These are tokens that
# appear in virtually every Indian address but carry no discriminating signal,
# so leaving them in lets an otherwise-unrelated address score misleadingly high.
_NOISE_TOKENS: frozenset[str] = frozenset(
    {
        "h",
        "hno",
        "no",
        "house",
        "flat",
        "plot",
        "st",
        "street",
        "road",
        "rd",
        "vill",
        "village",
        "gaon",
        "po",
        "post",
        "teh",
        "tehsil",
        "dist",
        "district",
        "state",
        "pin",
        "pincode",
        "india",
    }
)

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def normalize_address(raw: str | None) -> str:
    """Return a lowercase, punct-stripped, noise-word-free version of ``raw``.

    The result is a space-separated concatenation of the remaining tokens,
    suitable for fuzzy matching via ``rapidfuzz.fuzz.token_set_ratio``.
    """
    if not raw:
        return ""
    tokens = _WORD_RE.findall(raw.lower())
    kept = [t for t in tokens if t not in _NOISE_TOKENS]
    return " ".join(kept)


def addresses_match(
    a: str | None, b: str | None, threshold: float = 0.75
) -> bool:
    """Return True iff ``a`` and ``b`` normalise to a fuzzy-similar address.

    ``threshold`` is between 0.0 and 1.0 — the normalised token-set score.
    Default 0.75 is tuned on rural-microfinance test cases (H No + village +
    district + PIN spellings that differ across docs).
    """
    if not a or not b:
        return False
    na = normalize_address(a)
    nb = normalize_address(b)
    if not na or not nb:
        return False
    score = token_set_ratio(na, nb) / 100.0
    return score >= threshold


def _normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    return " ".join(raw.strip().lower().split())


def name_matches(a: str | None, b: str | None) -> bool:
    """Case- and whitespace-insensitive exact match for person names.

    Not fuzzy — used when we want an *exact* match (e.g., applicant name on
    CAM vs PAN). For fuzzy name match (CAM vs Equifax) use a dedicated helper.
    """
    if not a or not b:
        return False
    return _normalize_name(a) == _normalize_name(b)


def name_is_related_via_father_husband(
    *,
    owner_name: str | None,
    father_or_husband_name: str | None,
    candidate: str | None,
) -> bool:
    """Level 1 sub-step 5 rule: if the ration/electricity-bill owner is not the
    borrower, the borrower MUST appear as that owner's father/husband (s/o, w/o).

    Returns True iff ``candidate`` matches the bill's declared s/o or w/o.
    """
    if not father_or_husband_name or not candidate:
        return False
    return name_matches(father_or_husband_name, candidate)


# Generic Indian "placeholder" surnames frequently used to mask caste — Kumar,
# Devi, Singh, Lal, etc. When an electricity / ration bill is in the name of
# e.g. "ASOK KUMAR" but the applicant's father is "ASHOK BAROKA", the FIRST
# names typically match while the surnames don't, because rural utility-bill
# data-entry systems strip the real surname and substitute "Kumar" / "Devi"
# at sign-up time. The strict surname check would call this a stranger and
# block the loan; in practice it's the same person. ``has_generic_surname``
# +
# ``first_names_match`` together let L1 emit a soft (WARNING) flag instead
# of a hard (CRITICAL) gate-block, so the assessor sees the situation and
# either confirms or escalates to MD review.
_GENERIC_INDIAN_SURNAMES: frozenset[str] = frozenset(
    {
        "kumar",
        "kumari",
        "devi",
        "singh",
        "lal",
        "rani",
        "bai",
        "begum",
        "khatun",
        "khatoon",
        "ji",
        "prasad",
        "sharma",
        "yadav",
        # ``ben`` (Gujarat) and ``bhai`` (Gujarat / Maharashtra) — same caste-
        # masking pattern in those regions.
        "ben",
        "bhai",
    }
)


def has_generic_surname(name: str | None) -> str | None:
    """Return the generic surname if ``name``'s last token is one of the
    well-known caste-placeholder surnames; otherwise ``None``.

    Single-token names ("RAVI") return ``None`` — there's no surname to call
    generic. Names with 3+ tokens still check only the LAST token (so
    "ASOK BAROKA KUMAR" is treated as a generic-suffix case).
    """
    if not name:
        return None
    tokens = _normalize_name(name).split()
    if len(tokens) < 2:
        return None
    last = tokens[-1]
    return last if last in _GENERIC_INDIAN_SURNAMES else None


def first_names_match(a: str | None, b: str | None) -> bool:
    """Return True iff the FIRST tokens of ``a`` and ``b`` are an exact match
    after lowercase + whitespace normalisation.

    Companion to ``has_generic_surname``: when bill owner "ASOK KUMAR" and
    applicant's father "ASHOK BAROKA" share the same first name (modulo
    common spelling variants the caller can pre-normalise), and the
    surname is generic, treat the bill owner as the relative.

    Tolerates the common Indian spelling pair ASOK ↔ ASHOK and similar
    no-vowel-change drift via a small canonical-form pass: drops trailing
    'h' on the first token before comparing ("asok" == "ashok", "anil" ==
    "aneel" stays distinct because the consonant differs).
    """
    if not a or not b:
        return False
    af = _normalize_name(a).split()
    bf = _normalize_name(b).split()
    if not af or not bf:
        return False
    return _canonical_first_name(af[0]) == _canonical_first_name(bf[0])


def _canonical_first_name(tok: str) -> str:
    """Collapse the most common Indian spelling drift on first names.

    Drops every interior or trailing ``h`` whose immediate neighbour is a
    vowel (so "ashok" → "asok", "raghav" → "ragav") and collapses
    consecutive duplicate vowels ("aneel" → "anel"). Leading ``h`` is
    preserved — names like "harsh" or "himanshu" stay intact. The rule is
    deliberately narrow: only the spelling drift the user actually
    surfaced (ASOK ↔ ASHOK), nothing more — overly aggressive
    normalisation would collapse real distinctions like "anil" / "amit".
    """
    if not tok:
        return tok
    chars = list(tok)
    out: list[str] = []
    for i, ch in enumerate(chars):
        if (
            ch == "h"
            and i > 0  # never strip a leading 'h'
            and (
                chars[i - 1] in "aeiou"
                or (i + 1 < len(chars) and chars[i + 1] in "aeiou")
            )
        ):
            continue
        # Collapse consecutive duplicate vowels
        if out and ch in "aeiou" and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


def fuzzy_name_match(a: str | None, b: str | None, threshold: float = 0.85) -> bool:
    """Fuzzy name match — tolerates initials, order swap, minor spelling drift."""
    if not a or not b:
        return False
    score = token_set_ratio(_normalize_name(a), _normalize_name(b)) / 100.0
    return score >= threshold


def any_address_matches(primary: str | None, others: Iterable[str | None]) -> bool:
    """True if at least one of ``others`` fuzzy-matches ``primary``."""
    return any(addresses_match(primary, o) for o in others)


# ---------------------------------------------------------------------------
# Structured Aadhaar ↔ GPS comparison (used by Level 1 sub-step 4).
# ---------------------------------------------------------------------------
#
# Why the old "fuzzy full-string match" is wrong for Indian microfinance:
#
#  - Aadhaar prints a COARSE address (usually ends at district + pincode, e.g.
#    "Hisar, Haryana, 125001"). The applicant's actual village name rarely
#    survives in a clean token-set-ratio comparison.
#  - The house-visit GPS coordinate reverse-geocodes to a MUCH FINER address
#    ("Hisar II Block, Hisar, Haryana, 127045, India"). The last 3 digits of
#    the pincode almost always differ even when the applicant is on their own
#    doorstep — pincodes cover dozens of villages each.
#
# A token-set-ratio treats "125001 vs 127045" as a large penalty and falsely
# flags the pair as a mismatch. The correct comparison is hierarchical:
#
#   1. Same country? (must match)
#   2. Same state? (must match)
#   3. Same district? (must match — this is the strongest signal)
#   4. Same village/locality? (if known on both sides → strong confirmation;
#      if only one side has it → leave it at "doubtful" instead of CRITICAL)
#
# Verdict ladder:
#   "match"     — district + village both line up
#   "doubtful"  — district matches but village can't be confirmed
#   "mismatch"  — district or state differs
#
# Assessors can accept a "doubtful" with a note; only "mismatch" is CRITICAL.

_KNOWN_INDIAN_STATES: frozenset[str] = frozenset(
    {
        "andhra pradesh",
        "arunachal pradesh",
        "assam",
        "bihar",
        "chhattisgarh",
        "goa",
        "gujarat",
        "haryana",
        "himachal pradesh",
        "jharkhand",
        "karnataka",
        "kerala",
        "madhya pradesh",
        "maharashtra",
        "manipur",
        "meghalaya",
        "mizoram",
        "nagaland",
        "odisha",
        "punjab",
        "rajasthan",
        "sikkim",
        "tamil nadu",
        "telangana",
        "tripura",
        "uttar pradesh",
        "uttarakhand",
        "west bengal",
        # Union territories
        "delhi",
        "chandigarh",
        "puducherry",
        "jammu and kashmir",
        "ladakh",
    }
)

_PINCODE_RE = re.compile(r"\b(\d{6})\b")


@dataclass
class GPSMatch:
    """Result of a structured Aadhaar ↔ GPS comparison."""

    verdict: str  # "match" | "doubtful" | "mismatch"
    score: int  # 0-100 confidence in the match
    state_match: bool | None  # None = couldn't determine either side
    district_match: bool | None
    village_match: bool | None
    reason: str  # human-readable explanation for the assessor
    gps_state: str | None
    gps_district: str | None
    gps_village: str | None
    aadhaar_pincode: str | None
    # Pincode-master-resolved districts (India Post data.gov.in snapshot). When
    # populated these override the Nominatim / Aadhaar-text-derived districts
    # because the Post Office boundaries are the operative ones for recovery
    # and legal purposes — OSM boundaries are frequently slightly off.
    aadhaar_district_from_pincode: str | None = None
    gps_district_from_pincode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "state_match": self.state_match,
            "district_match": self.district_match,
            "village_match": self.village_match,
            "reason": self.reason,
            "gps_state": self.gps_state,
            "gps_district": self.gps_district,
            "gps_village": self.gps_village,
            "aadhaar_pincode": self.aadhaar_pincode,
            "aadhaar_district_from_pincode": self.aadhaar_district_from_pincode,
            "gps_district_from_pincode": self.gps_district_from_pincode,
        }


def _text_contains_name(haystack: str, needle: str, threshold: int = 85) -> bool:
    """Case-insensitive fuzzy substring check.

    Tolerates spelling drift (Haryana vs Hariyana, Chaudhriyas vs Chaudhriwas)
    by running ``partial_ratio`` across the candidate tokens.
    """
    if not haystack or not needle:
        return False
    hay = haystack.lower()
    ned = needle.lower().strip()
    if not ned:
        return False
    # Fast exact path first
    if ned in hay:
        return True
    # Fuzzy fallback
    return partial_ratio(hay, ned) >= threshold


def _find_state_in_text(text: str) -> str | None:
    """Return the canonical state name (lower-cased) if any known Indian state
    appears in ``text``."""
    low = text.lower()
    for state in _KNOWN_INDIAN_STATES:
        if state in low:
            return state
    # Handle common spelling variants by partial match on the whole text.
    for state in _KNOWN_INDIAN_STATES:
        if partial_ratio(low, state) >= 90:
            return state
    return None


def _extract_pincode(text: str) -> str | None:
    m = _PINCODE_RE.search(text)
    return m.group(1) if m else None


def compare_aadhaar_to_gps(
    *,
    aadhaar_address: str,
    gps_state: str | None,
    gps_district: str | None,
    gps_village: str | None,
    gps_pincode: str | None = None,
) -> GPSMatch:
    """Compare an Aadhaar free-text address to the GPS structured address.

    District-level match is required. Village-level match upgrades to a
    confident "match"; village differing OR unknown downgrades to "doubtful".
    A state or district mismatch is always a "mismatch".

    When *both* sides carry 6-digit pincodes that resolve via the bundled
    India Post master, those authoritative districts OVERRIDE the fuzzy
    text-based comparison. Pincode boundaries are what India Post, courts,
    and recovery agencies operate on — OSM/Nominatim administrative tags
    frequently disagree (e.g., a road tagged ``county=Hisar`` in OSM can
    physically fall under the Bhiwani postal district).
    """
    # Local import to avoid circular — pincode_lookup only needs this module's
    # GPSMatch type indirectly through the call graph, not at import time.
    from app.verification.services.pincode_lookup import lookup_pincode

    aadhaar_lc = (aadhaar_address or "").lower()
    pincode = _extract_pincode(aadhaar_address or "")
    aadhaar_pin_info = lookup_pincode(pincode)
    gps_pin_info = lookup_pincode(gps_pincode)

    aadhaar_district_from_pincode = (
        aadhaar_pin_info.district if aadhaar_pin_info else None
    )
    gps_district_from_pincode = gps_pin_info.district if gps_pin_info else None

    # ---- state check ----
    gps_state_clean = (gps_state or "").strip()
    if gps_state_clean:
        state_match: bool | None = _text_contains_name(aadhaar_lc, gps_state_clean)
    else:
        state_match = None

    # ---- district check ----
    # Preferred: India-Post-derived districts on BOTH sides → direct compare.
    # Fallback: fuzzy match Nominatim-side district against Aadhaar text.
    gps_district_clean = (gps_district or "").strip()
    if aadhaar_district_from_pincode and gps_district_from_pincode:
        district_match: bool | None = (
            aadhaar_district_from_pincode.strip().lower()
            == gps_district_from_pincode.strip().lower()
        )
    elif gps_district_clean:
        district_match = _text_contains_name(aadhaar_lc, gps_district_clean)
    else:
        district_match = None

    # ---- village / locality check ----
    gps_village_clean = (gps_village or "").strip()
    if gps_village_clean:
        # Drop administrative suffixes that aren't actual village names so
        # we don't credit a match just because both contain the district.
        candidate = re.sub(
            r"\b(block|ward|sector|zone|tehsil|taluk|mandal)\b\s*\w*",
            "",
            gps_village_clean,
            flags=re.IGNORECASE,
        ).strip()
        if candidate and candidate.lower() != gps_district_clean.lower():
            village_match: bool | None = _text_contains_name(aadhaar_lc, candidate)
        else:
            village_match = None
    else:
        village_match = None

    # ---- verdict ----
    if state_match is False:
        verdict = "mismatch"
        score = 10
        reason = (
            f"GPS resolves to state \"{gps_state}\" which does not appear in "
            f"the applicant's Aadhaar address."
        )
    elif (
        district_match is False
        and aadhaar_district_from_pincode
        and gps_district_from_pincode
    ):
        # Authoritative pincode-level disagreement: both sides mapped via
        # India Post and they point to different districts.
        verdict = "mismatch"
        score = 15
        reason = (
            f"Aadhaar pincode {pincode} is in {aadhaar_district_from_pincode} "
            f"district (India Post) but GPS pincode {gps_pincode} is in "
            f"{gps_district_from_pincode} district. The photo was taken in a "
            "different district from the applicant's Aadhaar registration — "
            "genuine mismatch."
        )
    elif district_match is False:
        verdict = "mismatch"
        score = 20
        reason = (
            f"GPS resolves to district \"{gps_district}\" which does not "
            f"appear in the applicant's Aadhaar address."
        )
    elif district_match is True and village_match is True:
        verdict = "match"
        score = 95
        reason = (
            f"District (\"{gps_district}\") and village (\"{gps_village}\") "
            "both match the applicant's Aadhaar address."
        )
    elif district_match is True and village_match is False:
        verdict = "doubtful"
        score = 60
        reason = (
            f"District (\"{gps_district}\") matches the Aadhaar address, but "
            f"the more specific locality (\"{gps_village}\") is not mentioned "
            "there. Could be a neighbouring village within the same district "
            "— assessor should confirm."
        )
    elif district_match is True and village_match is None:
        verdict = "doubtful"
        score = 75
        reason = (
            f"District (\"{gps_district}\") matches the Aadhaar address. "
            "Village-level confirmation was not possible — OpenStreetMap "
            "returned no village tag for these coordinates."
        )
    elif district_match is None and state_match is True:
        verdict = "doubtful"
        score = 50
        reason = (
            f"State (\"{gps_state}\") matches the Aadhaar address, but "
            "district-level data was not returned by the geocoder."
        )
    else:
        verdict = "doubtful"
        score = 40
        reason = (
            "Structured comparison inconclusive — geocoder returned limited "
            "address fields. Assessor should review the coordinates manually."
        )

    return GPSMatch(
        verdict=verdict,
        score=score,
        state_match=state_match,
        district_match=district_match,
        village_match=village_match,
        reason=reason,
        gps_state=gps_state,
        gps_district=gps_district,
        gps_village=gps_village,
        aadhaar_pincode=pincode,
        aadhaar_district_from_pincode=aadhaar_district_from_pincode,
        gps_district_from_pincode=gps_district_from_pincode,
    )
