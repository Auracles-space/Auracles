"""Pydantic schemas for the admin organization detail page.

Response models for the read-only panels platform admins open on one
organization: overview, members, verification, financials, frameworks,
attestations, and audit trail. Every schema exposes the minimum an admin
needs to judge the org — no payout account details, no raw S3 keys.

Maps to: organizations end-to-end design §Decision 1 and §Slice D.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AdminOrgUserRef(BaseModel):
    """A user reference resolved to a display name (actor, suspender, closer)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str


class AdminOrgCapabilityItem(BaseModel):
    """One commercial capability row and its admin-set status."""

    capability: str
    status: str
    status_reason: str | None


class AdminOrgOwnerItem(BaseModel):
    """An owner of the organization, with contact email for admins."""

    member_id: UUID
    user_id: UUID
    display_name: str
    email: str


class AdminOrgOverviewResponse(BaseModel):
    """Identity, KYB state, lifecycle state, capabilities, and owners."""

    id: UUID
    slug: str
    name: str
    country: str
    website: str | None
    description: str | None
    created_at: datetime
    kyb_status: str
    kyb_submitted_at: datetime | None
    kyb_verified_at: datetime | None
    legal_name: str | None
    registration_number: str | None
    suspended_at: datetime | None
    suspension_reason: str | None
    suspended_by: AdminOrgUserRef | None
    deactivated_at: datetime | None
    deactivation_reason: str | None
    deactivated_by: AdminOrgUserRef | None
    capabilities: list[AdminOrgCapabilityItem]
    member_count: int
    owners: list[AdminOrgOwnerItem]


class AdminOrgTeamRef(BaseModel):
    """A team a member sits on."""

    id: UUID
    name: str


class AdminOrgMemberItem(BaseModel):
    """One organization member with role and team placements."""

    member_id: UUID
    user_id: UUID
    display_name: str
    email: str
    role: str
    joined_at: datetime
    teams: list[AdminOrgTeamRef]


class AdminOrgMembersResponse(BaseModel):
    """Every member of the org plus the count of still-pending invitations."""

    members: list[AdminOrgMemberItem]
    pending_invitation_count: int


class AdminOrgDocumentLink(BaseModel):
    """A short-lived signed download link for one KYB document.

    ``download_url`` is null when the reserved upload never completed, so the
    admin sees the gap rather than a link to a missing object.
    """

    kind: str
    file_name: str
    download_url: str | None


class AdminOrgVerificationResponse(BaseModel):
    """The org's legal profile, KYB verdict, and signed document links."""

    legal_name: str | None
    registration_number: str | None
    address: dict[str, Any] | None
    kyb_status: str
    kyb_submitted_at: datetime | None
    kyb_verified_at: datetime | None
    kyb_review_notes: str | None
    tax_document_type: str | None
    documents: list[AdminOrgDocumentLink]


class AdminOrgPayoutsSummary(BaseModel):
    """Aggregate payout state for the org."""

    pending_count: int
    completed_total: Decimal
    last_payout_at: datetime | None


class AdminOrgPurchasesSummary(BaseModel):
    """Aggregate purchase state where the org was the buyer."""

    completed_count: int
    failed_count: int
    total_spent: Decimal


class AdminOrgPayoutItem(BaseModel):
    """One payout, without any payout account details."""

    payout_id: UUID
    amount: Decimal
    currency: str
    status: str
    provider: str | None
    initiated_at: datetime
    completed_at: datetime | None


class AdminOrgTransactionItem(BaseModel):
    """One transaction in which the org was payer or payee."""

    transaction_id: UUID
    transaction_type: str
    status: str
    amount: Decimal
    currency: str
    created_at: datetime


class AdminOrgFinancialsResponse(BaseModel):
    """Balances, payout and purchase summaries, and the latest ledger rows."""

    currency: str
    available_balance: Decimal
    pending_balance: Decimal
    payouts_summary: AdminOrgPayoutsSummary
    purchases_summary: AdminOrgPurchasesSummary
    recent_payouts: list[AdminOrgPayoutItem]
    recent_transactions: list[AdminOrgTransactionItem]


class AdminOrgFrameworkItem(BaseModel):
    """A Framework the org sells."""

    id: UUID
    title: str
    status: str
    created_at: datetime


class AdminOrgLicenseItem(BaseModel):
    """A License the org holds, with how many grants allocate it."""

    license_id: UUID
    framework_id: UUID
    framework_title: str
    status: str
    license_type: str
    created_at: datetime
    grant_count: int


class AdminOrgFrameworksResponse(BaseModel):
    """Frameworks owned and Licenses held by the org."""

    frameworks: list[AdminOrgFrameworkItem]
    licenses: list[AdminOrgLicenseItem]


class AdminOrgAttestationItem(BaseModel):
    """An in-flight Attestation the org is performing."""

    id: UUID
    status: str
    target_title: str | None
    reviewing_member_display_name: str | None
    completion_due_at: datetime | None
    created_at: datetime


class AdminOrgAttestationCounts(BaseModel):
    """How many of the org's Attestations are in flight versus finished."""

    in_flight: int
    completed: int


class AdminOrgAttestationsResponse(BaseModel):
    """In-flight Attestations and in-flight/finished counts."""

    attestations: list[AdminOrgAttestationItem]
    counts: AdminOrgAttestationCounts


class AdminOrgAuditItem(BaseModel):
    """One audit event about the org, with the actor resolved."""

    log_id: UUID
    actor: AdminOrgUserRef | None
    action: str
    target_type: str
    target_id: UUID | None
    metadata: dict[str, Any]
    created_at: datetime


class AdminOrgAuditResponse(BaseModel):
    """A page of the org's audit trail, newest first."""

    items: list[AdminOrgAuditItem]
    total: int
    page: int
    page_size: int
