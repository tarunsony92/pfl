"""Indian pincode → district / taluk lookup, backed by a bundled snapshot of
``data.gov.in/all_india_pin_code.csv``.

Why this exists
---------------
Indian microfinance cases are concentrated in rural areas where the
**Aadhaar-printed pincode** often covers dozens of villages — so a fuzzy
string match against the Aadhaar address text can conclude "districts differ"
when the applicant is literally on their own doorstep. At the same time,
OpenStreetMap / Nominatim administrative boundaries don't always match India
Post's boundaries (a road tagged with ``county=Hisar`` in OSM may physically
fall under the ``Bhiwani`` postal district). When the two disagree, India
Post is the operative source of truth for verification decisions because it
is what the courts + recovery agencies go by.

The bundled file is a state-filtered (Haryana-only for now) slice of the
official ``all_india_pin_code.csv`` snapshot.  Add further states by running
``scripts/bake_pincode_master.py`` against the raw file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_HARYANA_FILE = _DATA_DIR / "haryana_pincodes.json"


@dataclass(frozen=True)
class PincodeInfo:
    pincode: str
    district: str
    taluk: str | None
    state: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "pincode": self.pincode,
            "district": self.district,
            "taluk": self.taluk,
            "state": self.state,
        }


@lru_cache(maxsize=1)
def _load_master() -> dict[str, PincodeInfo]:
    """Load every bundled state file into one flat dict keyed by pincode."""
    out: dict[str, PincodeInfo] = {}
    for path, state in ((_HARYANA_FILE, "Haryana"),):
        if not path.exists():
            _log.warning("pincode_lookup: missing bundled master at %s", path)
            continue
        try:
            body = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001
            _log.warning("pincode_lookup: cannot parse %s: %s", path, exc)
            continue
        for pincode, rec in (body.get("pincodes") or {}).items():
            out[pincode] = PincodeInfo(
                pincode=pincode,
                district=(rec.get("district") or "").strip(),
                taluk=(rec.get("taluk") or None),
                state=state,
            )
    _log.info("pincode_lookup: loaded %d master rows", len(out))
    return out


def lookup_pincode(pincode: str | None) -> PincodeInfo | None:
    """Return canonical district/taluk for a 6-digit pincode, or None.

    ``pincode`` is matched exactly; the caller is responsible for regex-
    extracting it from free-text address blocks.
    """
    if not pincode:
        return None
    pin = pincode.strip()
    if len(pin) != 6 or not pin.isdigit():
        return None
    return _load_master().get(pin)


def master_size() -> int:
    """Number of pincodes currently covered by the bundled master."""
    return len(_load_master())
