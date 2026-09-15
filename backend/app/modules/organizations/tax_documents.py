"""Tax document types an organization may declare, by country.

US IRS forms (W-9, W-8BEN) mean nothing to a Nigerian organization, and a FIRS
TIN certificate or Tax Clearance Certificate means nothing elsewhere, so the
accepted types depend on the organization's country. ``other`` stays open to
every country for exemptions and documents without a dedicated type.

Maps to: FR-ATT org-attestor tax document gate; Nigeria pilot market.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.shared.errors import error_detail

NIGERIAN_TAX_DOCUMENT_TYPES: frozenset[str] = frozenset({"firs_tin", "tcc", "other"})
DEFAULT_TAX_DOCUMENT_TYPES: frozenset[str] = frozenset({"w9", "w8ben", "other"})


def allowed_tax_document_types(country: str) -> frozenset[str]:
    """Return the tax document types an organization in ``country`` may declare.

    Args:
        country: ISO 3166-1 alpha-2 country code of the organization.

    Returns:
        The set of accepted ``tax_document_type`` values.
    """
    if country.upper() == "NG":
        return NIGERIAN_TAX_DOCUMENT_TYPES
    return DEFAULT_TAX_DOCUMENT_TYPES


def ensure_tax_document_type_allowed(country: str, tax_document_type: str) -> None:
    """Refuse a tax document type that does not belong to the org's country.

    Args:
        country: ISO 3166-1 alpha-2 country code of the organization.
        tax_document_type: The declared document type.

    Raises:
        HTTPException(422): ``tax_document_type_not_allowed`` on a mismatch.
    """
    if tax_document_type not in allowed_tax_document_types(country):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error_detail(
                "tax_document_type_not_allowed",
                "This tax document type is not accepted for your "
                "organization's country.",
            ),
        )
