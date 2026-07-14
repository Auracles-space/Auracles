"""Canonical Framework taxonomy values accepted by contributor write APIs.

Re-exports the shared marketplace taxonomy so Framework writes and Attestor
matching validate against one identical vocabulary.
"""

from __future__ import annotations

from app.shared.taxonomy import (
    FrameworkCategory,
    FrameworkFunction,
    FrameworkIndustry,
    FrameworkSector,
)

__all__ = [
    "FrameworkCategory",
    "FrameworkFunction",
    "FrameworkIndustry",
    "FrameworkSector",
]
