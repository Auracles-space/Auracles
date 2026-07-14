"""Pure value-remap tables for attestor taxonomy unification.

Kept import-safe outside Alembic context so the mappings can be unit tested and
reused by the migration without duplication.
"""

from __future__ import annotations

SECTOR_MAP: dict[str, str] = {
    "PE": "private_equity",
    "VC": "venture_capital",
    "Infrastructure": "infrastructure",
    "Real Estate": "real_estate",
}

FUNCTION_MAP: dict[str, str] = {
    "Compliance": "compliance",
    "Governance": "governance",
    "Risk": "risk_management",
    "Operations": "operations",
    "Legal": "legal",
    "Finance": "finance",
    "HR": "human_resources",
    "Technology": "engineering",
    "Investment Management": "investment_management",
}

JURISDICTION_MAP: dict[str, str] = {
    "Global": "global",
    "European Union": "european_union",
    "Australia": "australia",
    "Brazil": "brazil",
    "Canada": "canada",
    "China": "china",
    "France": "france",
    "Germany": "germany",
    "Hong Kong": "hong_kong",
    "India": "india",
    "Ireland": "ireland",
    "Japan": "japan",
    "Kenya": "kenya",
    "Mexico": "mexico",
    "Netherlands": "netherlands",
    "New Zealand": "new_zealand",
    "Nigeria": "nigeria",
    "Saudi Arabia": "saudi_arabia",
    "Singapore": "singapore",
    "South Africa": "south_africa",
    "Switzerland": "switzerland",
    "United Arab Emirates": "united_arab_emirates",
    "United Kingdom": "united_kingdom",
    "United States": "united_states",
}


def _remap_array(values: list[str], mapping: dict[str, str]) -> list[str]:
    """Remap known values while preserving unknown values verbatim."""
    return [mapping.get(value, value) for value in values]
