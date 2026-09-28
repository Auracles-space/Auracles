"""Response schemas for the public demand map.

Nothing here carries an identity. Every row is a count of distinct searchers
that has already cleared the aggregation floor, so the payload describes a
market rather than any person in it.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class DemandTerm(BaseModel):
    """One search term people looked for and did not find."""

    term: str
    searcher_count: int = Field(ge=1)


class DemandFilterCombination(BaseModel):
    """One combination of catalogue filters that returned nothing."""

    filters: dict[str, str]
    searcher_count: int = Field(ge=1)


class DemandMapResponse(BaseModel):
    """Unmet demand across the reporting window.

    ``min_searchers`` is returned so the page can state the floor rather than
    imply the list is exhaustive: anything quieter than this is deliberately
    absent.
    """

    terms: list[DemandTerm]
    filters: list[DemandFilterCombination]
    period_from: date
    min_searchers: int
