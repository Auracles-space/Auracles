"""Canonical controlled taxonomy shared across marketplace subsystems.

Single source of truth for Sector, Function, Category, Industry, and
Jurisdiction vocabularies used by Framework writes, Explore filters, and
Attestor specialization plus AMM matching.
"""

from __future__ import annotations

from typing import Literal, get_args

FrameworkCategory = Literal[
    "framework",
    "playbook",
    "sop",
    "policy",
    "template",
    "toolkit",
    "assessment",
    "control_matrix",
    "workflow",
    "training_program",
]

FrameworkSector = Literal[
    "private_equity",
    "venture_capital",
    "infrastructure",
    "real_estate",
    "healthcare",
    "manufacturing",
    "government",
    "education",
    "financial_services",
    "energy",
    "telecommunications",
    "technology",
]

FrameworkIndustry = Literal[
    "fund_management",
    "portfolio_operations",
    "energy_infrastructure",
    "transportation_infrastructure",
    "residential_real_estate",
    "commercial_real_estate",
    "property_management",
    "healthcare_providers",
    "health_technology",
    "medical_devices",
    "software_engineering",
    "data_centers",
    "renewable_energy",
    "public_sector_agencies",
]

FrameworkFunction = Literal[
    "governance",
    "compliance",
    "risk_management",
    "operations",
    "finance",
    "legal",
    "engineering",
    "human_resources",
    "sales",
    "marketing",
    "product",
    "data_ai",
    "information_security",
    "investment_management",
]

CATEGORIES: frozenset[str] = frozenset(get_args(FrameworkCategory))
SECTORS: frozenset[str] = frozenset(get_args(FrameworkSector))
INDUSTRIES: frozenset[str] = frozenset(get_args(FrameworkIndustry))
FUNCTIONS: frozenset[str] = frozenset(get_args(FrameworkFunction))

JURISDICTIONS: frozenset[str] = frozenset(
    {
        "global",
        "european_union",
        "australia",
        "brazil",
        "canada",
        "china",
        "france",
        "germany",
        "hong_kong",
        "india",
        "ireland",
        "japan",
        "kenya",
        "mexico",
        "netherlands",
        "new_zealand",
        "nigeria",
        "saudi_arabia",
        "singapore",
        "south_africa",
        "switzerland",
        "united_arab_emirates",
        "united_kingdom",
        "united_states",
    }
)


def _validate(values: list[str], allowed: frozenset[str], label: str) -> list[str]:
    """Trim, de-duplicate first-seen values, and reject unknown entries."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if item not in allowed:
            raise ValueError(f"{item!r} is not a valid {label}.")
        if item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    if not cleaned:
        raise ValueError(f"at least one {label} is required.")
    return cleaned


def validate_sectors(values: list[str]) -> list[str]:
    """Validate sector slugs against the canonical set."""
    return _validate(values, SECTORS, "sector")


def validate_functions(values: list[str]) -> list[str]:
    """Validate function slugs against the canonical set."""
    return _validate(values, FUNCTIONS, "function")


def validate_jurisdictions(values: list[str]) -> list[str]:
    """Validate jurisdiction slugs against the canonical set."""
    return _validate(values, JURISDICTIONS, "jurisdiction")
