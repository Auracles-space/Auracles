"""Canonical Framework taxonomy values accepted by contributor write APIs.

These values mirror the current marketplace taxonomy used by the frontend form
and Explore filters. Response schemas intentionally remain string-based so
legacy rows with older labels can still be read while new writes are controlled.
"""

from __future__ import annotations

from typing import Literal

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
]
