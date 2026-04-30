"""Memory loader for Phase 1 Decisioning Engine (M5).

Provides cached access to static policy rules and heuristics markdown.
Both are loaded on first access and cached with ``functools.lru_cache``.
Call ``reset_caches()`` in tests or after a hot-reload to force re-reads.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_MEM_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def load_policy() -> dict[str, object]:
    """Load and return the parsed ``policy.yaml`` as a Python dict.

    Cached on first call; call ``reset_caches()`` to invalidate.
    """
    text = (_MEM_DIR / "policy.yaml").read_text(encoding="utf-8")
    data: dict[str, object] = yaml.safe_load(text)
    return data


@lru_cache(maxsize=1)
def load_heuristics() -> str:
    """Return the raw markdown text of ``heuristics.md``.

    Cached on first call; call ``reset_caches()`` to invalidate.
    """
    return (_MEM_DIR / "heuristics.md").read_text(encoding="utf-8")


def reset_caches() -> None:
    """Clear all lru_cache entries — useful in tests and after hot-reload."""
    load_policy.cache_clear()
    load_heuristics.cache_clear()
