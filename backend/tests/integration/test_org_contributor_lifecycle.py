"""End-to-end lifecycle test for organizations as Contributors.

Drives one contributor organization through the shipped real-endpoint journey:
capability activation → member-authored Framework draft/upload/submit →
admin publish → Operator purchase completion to org earnings → owner-managed
shared legal identity and payout setup → public org identity on explore and
directory → org Project bid, staffed delivery, escrow release, and org credit.

Provider callbacks and time-based clearance are out-of-band, so Stripe webhook
verification, payout-account verification, deliverable scan completion, and the
refund-window ageing step are seeded directly. All organization state changes
under test run through HTTP endpoints.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select, update

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.modules.financials.models import Escrow, Payout, PayoutAccount, Transaction
from app.modules.frameworks import service as framework_service
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    Review,
)
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.modules.invoicing.models import Invoice
from app.modules.organizations.models import OrgContributorProfile, OrgLegalProfile
from app.modules.projects import milestone_service
from app.modules.projects.models import Deliverable, Milestone, Project, Proposal
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.modules.workspace.models import WorkspaceMessage
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_organizations_endpoints import add_member, auth, create_org
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio


class FakeStripeCustomer:
    """Small stand-in for a Stripe Customer result."""

    def __init__(self, customer_id: str) -> None:
        """Store the provider customer id."""
        self.id = customer_id


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store the provider intent id and browser client secret."""
        self.id = payment_intent_id
        self.client_secret = client_secret


class CombinedStorage:
    """S3 storage test double for uploads and public preview reads."""

    def __init__(self) -> None:
        """Create empty fake S3 state."""
        self.existing_keys: set[str] = set()
        self.presigned_posts: list[tuple[str, str, str, int, int]] = []
        self.presigned_gets: list[tuple[str, str, int]] = []
        self.copy_requests: list[tuple[str, str, str, str]] = []

    def presigned_post(
        self,
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Return a deterministic fake artifact presigned POST policy."""
        self.presigned_posts.append((bucket, key, mime_type, max_size, expires_in))
        return {
            "url": f"https://s3.test/{bucket}",
            "fields": {
                "key": key,
                "Content-Type": mime_type,
                "policy": "fake-policy",
                "x-amz-signature": "fake-signature",
            },
        }

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a deterministic fake preview URL."""
        self.presigned_gets.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}?expires={expires_in}"

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return whether the fake object was marked uploaded."""
        del bucket
        return key in self.existing_keys

    def copy_object(
        self,
        source_bucket: str,
        source_key: str,
        destination_bucket: str,
        destination_key: str,
    ) -> None:
        """Record a copy and mark the destination object as present."""
        self.copy_requests.append(
            (source_bucket, source_key, destination_bucket, destination_key)
        )
        self.existing_keys.add(destination_key)

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Record an upload and mark the destination object as present."""
        del bucket, body, mime_type
        self.existing_keys.add(key)

    def delete_object(self, bucket: str, key: str) -> None:
        """Remove a fake object if present."""
        del bucket
        self.existing_keys.discard(key)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def lifecycle_context(migrated_database: None) -> AsyncIterator[dict[str, Any]]:
    """Reset contributor lifecycle rows and install fake Redis plus fake S3."""
    from app.integrations import s3

    del migrated_database
    fake_redis = FakeRedis()
    fake_storage = CombinedStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete all touched rows in foreign-key-safe order."""
        async with async_session_factory() as session:
            await session.execute(update(Framework).values(preview_artifact_id=None))
            await session.execute(delete(WebhookEvent))
            await session.execute(delete(Invoice))
            await session.execute(delete(Payout))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(WorkspaceMessage))
            await session.execute(delete(Review))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(License))
            await session.execute(delete(ArtifactRarityAudit))
            await session.execute(delete(ArtifactPiiAudit))
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Artifact))
            await session.execute(delete(Deliverable))
            await session.execute(delete(Milestone))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(Framework))
            await session.execute(delete(Project))
            await session.execute(delete(Proposal))
            await session.execute(delete(OrgLegalProfile))
            await session.execute(delete(OrgContributorProfile))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    original_storage = s3.storage
    s3.storage = fake_storage
    try:
        yield {"redis": fake_redis, "storage": fake_storage}
    finally:
        s3.storage = original_storage
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(
    prefix: str,
    *,
    roles: list[str] | None = None,
    kyc_status: str = "verified",
    totp_secret: str | None = None,
) -> UUID:
    """Create a verified user with optional roles and TOTP; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                kyc_status=kyc_status,
                totp_enabled=totp_secret is not None,
                totp_secret=(
                    encrypt_totp_secret(totp_secret)
                    if totp_secret is not None
                    else None
                ),
            )
            session.add(user)
            await session.flush()
            for role in roles or []:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        source="self",
                        approved_at=datetime.now(UTC),
                    )
                )
            return user.id


def _headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for one user and explicit role claims."""
    return {"Authorization": f"Bearer {create_access_token(user_id, roles)}"}


def _framework_payload() -> dict[str, Any]:
    """Return a valid org framework create payload."""
    return {
        "title": "Lifecycle Org Framework",
        "description": "A contributor Framework authored under an organization.",
        "category": "framework",
        "sector": "financial_services",
        "industry": "fund_management",
        "function": "risk_management",
        "tags": ["org", "lifecycle"],
        "jurisdiction": "GB",
        "complexity": 3,
        "org_size": "mid_market",
        "lifecycle_stage": "scale",
        "pricing": {
            "price": "499.00",
            "currency": "USD",
            "license_types": ["single_user"],
            "commercial_rights": "Internal commercial use allowed.",
            "usage_restrictions": "No resale.",
        },
    }


def _project_payload() -> dict[str, Any]:
    """Return a valid Project create payload."""
    return {
        "title": "Lifecycle Project",
        "description": "Build a procurement operating model.",
        "category": "operations",
        "required_deliverables": [
            {"name": "Playbook", "description": "Implementation guide"}
        ],
        "budget_min": "1000.00",
        "budget_max": "2000.00",
        "currency": "USD",
        # Relative to today: the API rejects a deadline in the past, so a
        # literal date passes only until it elapses.
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
    }


def _org_proposal_payload(delivering_member_id: UUID) -> dict[str, Any]:
    """Return a valid organization Proposal create payload."""
    return {
        "delivering_member_id": str(delivering_member_id),
        "scope": "I will deliver the procurement model and rollout plan.",
        "budget": "1500.00",
        "timeline_days": 21,
        "deliverables": [
            {"name": "Operating model", "description": "Documented model"}
        ],
    }


def _payment_intent_event(
    event_id: str,
    *,
    transaction_id: UUID,
    framework_id: UUID,
    kind: str = "purchase",
    provider_ref: str,
    license_type: str = "single_user",
    extra_metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a Stripe PaymentIntent event payload for webhook completion."""
    metadata = {
        "transaction_id": str(transaction_id),
        "kind": kind,
        "framework_id": str(framework_id),
        "license_type": license_type,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return {
        "id": event_id,
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": provider_ref, "metadata": metadata}},
    }


async def _mark_framework_pipeline_passed(framework_id: UUID) -> None:
    """Advance a submitted Framework to ``pipeline_passed`` for publish tests.

    Also designates a current Artifact as the preview so the Framework meets
    the publish-time preview requirement.
    """
    async with async_session_factory() as session:
        async with session.begin():
            framework = await session.get(Framework, framework_id)
            assert framework is not None
            framework.status = "pipeline_passed"
            framework.pipeline_failure_reasons = {}
            artifact_id = await session.scalar(
                select(Artifact.id).where(
                    Artifact.framework_id == framework_id,
                    Artifact.current_for_framework.is_(True),
                )
            )
            framework.preview_artifact_id = artifact_id


async def _age_transaction(transaction_id: UUID, *, hours: int) -> None:
    """Move a transaction into the past so refund-window clearance can elapse."""
    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.get(Transaction, transaction_id)
            assert transaction is not None
            transaction.created_at = datetime.now(UTC) - timedelta(hours=hours)


async def _mark_org_payout_account_verified(org_id: UUID) -> UUID:
    """Mark the org's latest payout account verified and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            account = await session.scalar(
                select(PayoutAccount)
                .where(PayoutAccount.org_id == org_id)
                .order_by(PayoutAccount.created_at.desc())
            )
            assert account is not None
            account.verified_at = datetime.now(UTC)
            return account.id


async def _mark_deliverable_visible(deliverable_id: UUID) -> None:
    """Mark a submitted Deliverable as virus-scan visible for approval."""
    async with async_session_factory() as session:
        async with session.begin():
            deliverable = await session.get(Deliverable, deliverable_id)
            assert deliverable is not None
            deliverable.scan_status = "visible"


async def test_org_contributor_full_lifecycle(
    client: AsyncClient,
    lifecycle_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One organization travels activation → sale → payout → project delivery.

    Proves the shipped endpoints compose: capability activation grants the
    derived member role, a member authors and submits real Framework artifacts,
    an owner publishes and the sale completes to org earnings, the owner sets
    up the shared legal identity and payout path, public marketplace surfaces
    show only the org identity, and project delivery releases milestone funds
    to the organization rather than a member.
    """
    del lifecycle_context

    owner_secret = pyotp.random_base32()
    owner_id = await _create_user("org-owner", totp_secret=owner_secret)
    member_id = await _create_user("org-member")
    operator_id = await _create_user("operator", roles=["operator"])
    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    operator_headers = _headers(operator_id, ["operator"])
    org = await create_org(client, owner_token, "org-contributor-lifecycle")
    org_id = UUID(str(org["id"]))
    member_row_id = await add_member(str(org["id"]), member_id, "member")

    queued_payouts: list[str] = []
    webhook_state: dict[str, Any] = {"event": None}

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Return a stable Stripe customer id for purchase and escrow flows."""
        del email, name, idempotency_key
        return FakeStripeCustomer("cus_lifecycle_123")

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        """Return deterministic PaymentIntent ids for purchase and escrow flows."""
        del customer_id, amount, currency, idempotency_key
        if metadata.get("kind") == "escrow":
            return FakeStripePaymentIntent(
                "pi_lifecycle_escrow_123",
                "pi_lifecycle_escrow_secret",
            )
        return FakeStripePaymentIntent(
            "pi_lifecycle_purchase_123",
            "pi_lifecycle_purchase_secret",
        )

    async def fake_create_express_account(
        *,
        email: str,
        country: str,
    ) -> SimpleNamespace:
        """Return a deterministic org payout-account provider id."""
        del email, country
        return SimpleNamespace(id=f"acct_{uuid4().hex}")

    async def fake_create_account_link(
        *,
        account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> SimpleNamespace:
        """Return a deterministic Stripe Connect onboarding link."""
        del account_id, refresh_url, return_url
        return SimpleNamespace(url="https://connect.stripe.test/onboard")

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Return the preloaded webhook event for Stripe callback tests."""
        del payload
        if signature_header != "valid-signature":
            raise AssertionError("unexpected signature in lifecycle test")
        event = webhook_state["event"]
        assert isinstance(event, dict)
        return event

    class _NoopTask:
        """Task double that only records dispatched ids."""

        def delay(self, identifier: str) -> None:
            queued_payouts.append(identifier)

    class _NoopInvoiceTask:
        """Task double for invoice generation side effects."""

        def delay(self, transaction_id: str) -> None:
            del transaction_id

    class _NoopScanTask:
        """Task double for deliverable scan dispatch."""

        def delay(self, deliverable_id: str) -> None:
            del deliverable_id

    async def _noop_pipeline(*args: object, **kwargs: object) -> None:
        return None

    async def _noop_index(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        financials_service.stripe,
        "create_customer",
        fake_create_customer,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )
    monkeypatch.setattr(
        milestone_service.stripe,
        "create_customer",
        fake_create_customer,
    )
    monkeypatch.setattr(
        milestone_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "create_express_account",
        fake_create_express_account,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "create_account_link",
        fake_create_account_link,
    )
    monkeypatch.setattr(
        webhook_service.stripe,
        "verify_webhook",
        fake_verify_webhook,
    )
    monkeypatch.setattr(
        webhook_service,
        "generate_invoice_pdf",
        _NoopInvoiceTask(),
        raising=False,
    )
    monkeypatch.setattr(
        financials_service,
        "process_payout",
        _NoopTask(),
        raising=False,
    )
    monkeypatch.setattr(
        milestone_service,
        "scan_deliverable_upload",
        _NoopScanTask(),
    )
    monkeypatch.setattr(
        framework_service,
        "evaluate_framework_pipeline",
        _noop_pipeline,
    )
    monkeypatch.setattr(framework_service, "index_framework_artifacts", _noop_index)

    # --- Capability activation ------------------------------------------
    activated = await client.post(
        f"/v1/orgs/{org['id']}/contributor-capability/activate",
        headers=auth(owner_token),
    )
    assert activated.status_code == 200

    # Activating the org capability alone grants the derived role to owners and
    # admins only. A plain member reaches it through a team the capability is
    # enabled on, so the lifecycle walks that path before authoring anything.
    team = await client.post(
        f"/v1/orgs/{org['id']}/teams",
        json={"name": "Authoring"},
        headers=auth(owner_token),
    )
    assert team.status_code == 201
    team_id = team.json()["id"]
    team_capability = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/contributor",
        headers=auth(owner_token),
    )
    assert team_capability.status_code == 204
    team_member = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{member_row_id}",
        headers=auth(owner_token),
    )
    assert team_member.status_code == 204

    async with async_session_factory() as session:
        derived_role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_id,
                UserRole.role == "contributor",
                UserRole.source == "derived",
            )
        )
    assert derived_role is not None
    member_contributor_headers = _headers(member_id, ["contributor"])

    # --- Member authors and submits a Framework -------------------------
    created_framework = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_framework_payload(),
        headers=auth(member_token),
    )
    assert created_framework.status_code == 201
    framework_id = UUID(created_framework.json()["id"])

    upload = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "framework.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=auth(member_token),
    )
    assert upload.status_code == 200
    from app.integrations import s3

    assert hasattr(s3.storage, "existing_keys")
    s3.storage.existing_keys.add(upload.json()["file_key"])

    confirmed = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts/confirm",
        json={"artifact_id": upload.json()["artifact_id"]},
        headers=auth(member_token),
    )
    assert confirmed.status_code == 200

    submitted = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/submit",
        headers=auth(member_token),
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"

    await _mark_framework_pipeline_passed(framework_id)

    published = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/publish",
        headers=auth(owner_token),
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    # --- Operator purchase completes to the organization ----------------
    purchase = await client.post(
        f"/v1/financials/purchase/{framework_id}",
        headers=operator_headers,
        json={"license_type": "single_user"},
    )
    assert purchase.status_code == 200
    purchase_transaction_id = UUID(purchase.json()["transaction_id"])

    webhook_state["event"] = _payment_intent_event(
        "evt_lifecycle_purchase",
        transaction_id=purchase_transaction_id,
        framework_id=framework_id,
        provider_ref="pi_lifecycle_purchase_123",
    )
    purchase_webhook = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    assert purchase_webhook.status_code == 200
    assert purchase_webhook.json() == {"received": True, "status": "processed"}

    async with async_session_factory() as session:
        purchase_transaction = await session.get(Transaction, purchase_transaction_id)
        purchase_license = await session.scalar(
            select(License).where(License.transaction_id == purchase_transaction_id)
        )
    assert purchase_transaction is not None
    assert purchase_transaction.status == "completed"
    assert purchase_transaction.payee_org_id == org_id
    assert purchase_transaction.payee_id is None
    assert purchase_license is not None

    await _age_transaction(purchase_transaction_id, hours=72)

    earnings = await client.get(
        f"/v1/orgs/{org['id']}/financials/earnings",
        headers=auth(owner_token),
    )
    assert earnings.status_code == 200
    assert earnings.json() == {
        "currency": "USD",
        "gross_revenue": "499.00",
        "pending_clearance": "0.00",
        "available_balance": "424.15",
        "commission_rate": "0.15",
        "minimum_payout": "50.00",
    }

    # --- Owner configures legal identity, payout account, and payout ----
    legal_profile = await client.put(
        f"/v1/orgs/{org['id']}/legal-profile",
        headers=auth(owner_token),
        json={
            "legal_name": "Lifecycle Contributor LLC",
            "registration_number": "RC-445566",
            "address": {"country": "GB", "city": "London"},
            "totp_code": pyotp.TOTP(owner_secret).now(),
        },
    )
    assert legal_profile.status_code == 200

    payout_account_onboard = await client.post(
        f"/v1/orgs/{org['id']}/financials/payout-accounts",
        headers=auth(owner_token),
        json={
            "provider": "stripe",
            "refresh_url": "https://app.test/refresh",
            "return_url": "https://app.test/return",
        },
    )
    assert payout_account_onboard.status_code == 200
    payout_account_id = await _mark_org_payout_account_verified(org_id)

    tax_document = await client.post(
        f"/v1/orgs/{org['id']}/legal-profile/tax-document",
        headers=auth(owner_token),
        json={
            "tax_document_type": "w9",
            "file_name": "w9.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
        },
    )
    assert tax_document.status_code == 200
    assert tax_document.json()["s3_key"].startswith(
        f"org-legal-profiles/{org['id']}/tax-documents/"
    )

    payout = await client.post(
        f"/v1/orgs/{org['id']}/financials/payouts",
        headers=auth(owner_token),
        json={
            "amount": "100.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
            "totp_code": pyotp.TOTP(owner_secret).now(),
        },
    )
    assert payout.status_code == 200

    async with async_session_factory() as session:
        payout_row = await session.scalar(select(Payout))
    assert payout_row is not None
    assert payout_row.org_id == org_id
    assert payout_row.contributor_id is None
    assert queued_payouts == [str(payout_row.id)]

    # --- Public identity shows only the organization --------------------
    catalog = await client.get("/v1/explore/frameworks")
    assert catalog.status_code == 200
    catalog_item = next(
        item
        for item in catalog.json()["items"]
        if item["id"] == str(framework_id)
    )
    assert catalog_item["contributor_org_id"] == str(org_id)
    assert catalog_item["contributor_name"] == org["name"]
    assert "authoring_member_id" not in catalog_item

    framework_detail = await client.get(f"/v1/explore/frameworks/{framework_id}")
    assert framework_detail.status_code == 200
    assert framework_detail.json()["contributor_org_id"] == str(org_id)
    assert framework_detail.json()["contributor_name"] == org["name"]
    assert "authoring_member_id" not in framework_detail.json()

    contributor_directory = await client.get("/v1/contributors")
    assert contributor_directory.status_code == 200
    directory_item = next(
        item
        for item in contributor_directory.json()["contributors"]
        if item["org_id"] == str(org_id)
    )
    assert directory_item["slug"] == org["slug"]
    assert directory_item["published_framework_count"] == 1
    assert directory_item["member_count"] == 2

    contributor_profile = await client.get(f"/v1/contributors/{org['slug']}")
    assert contributor_profile.status_code == 200
    assert contributor_profile.json()["org_id"] == str(org_id)

    # --- Project bid, staffed delivery, and org release -----------------
    created_project = await client.post(
        "/v1/projects",
        headers=operator_headers,
        json=_project_payload(),
    )
    assert created_project.status_code == 201
    project_id = created_project.json()["id"]

    submitted_proposal = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(member_row_id),
    )
    assert submitted_proposal.status_code == 201
    proposal_id = submitted_proposal.json()["id"]

    accepted_proposal = await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )
    assert accepted_proposal.status_code == 200

    milestone = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=member_contributor_headers,
        json={
            "sequence": 1,
            "name": "Implementation",
            "description": "Build the approved procurement model.",
            "budget": "1500.00",
            "currency": "USD",
        },
    )
    assert milestone.status_code == 201
    milestone_id = milestone.json()["id"]

    finalized = await client.post(
        f"/v1/projects/{project_id}/milestones/finalize",
        headers=member_contributor_headers,
    )
    assert finalized.status_code == 200

    funded = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=operator_headers,
    )
    assert funded.status_code == 200
    milestone_transaction_id = UUID(funded.json()["transaction_id"])

    webhook_state["event"] = _payment_intent_event(
        "evt_lifecycle_escrow",
        transaction_id=milestone_transaction_id,
        framework_id=UUID(milestone_id),
        kind="escrow",
        provider_ref="pi_lifecycle_escrow_123",
        extra_metadata={
            "project_id": project_id,
            "milestone_id": milestone_id,
            "release_conditions": json.dumps(
                {
                    "kind": "project_milestone",
                    "project_id": project_id,
                    "milestone_id": milestone_id,
                    "approver_user_id": str(operator_id),
                }
            ),
        },
    )
    escrow_webhook = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    assert escrow_webhook.status_code == 200

    deliverable = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables",
        headers=member_contributor_headers,
        json={
            "name": "Operating model",
            "description": "Final operating model deliverable.",
            "file_keys": ["workspace/project/final-playbook.pdf"],
        },
    )
    assert deliverable.status_code == 201
    deliverable_id = UUID(deliverable.json()["id"])
    await _mark_deliverable_visible(deliverable_id)

    approved_deliverable = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables/"
        f"{deliverable_id}/approve",
        headers=operator_headers,
    )
    assert approved_deliverable.status_code == 200

    async with async_session_factory() as session:
        milestone_transaction = await session.get(Transaction, milestone_transaction_id)
        milestone_escrow = await session.scalar(
            select(Escrow).where(Escrow.ref_id == UUID(milestone_id))
        )
        project_row = await session.get(Project, UUID(project_id))
    assert milestone_transaction is not None
    assert milestone_transaction.status == "completed"
    assert milestone_transaction.payee_org_id == org_id
    assert milestone_transaction.payee_id is None
    assert milestone_escrow is not None
    assert milestone_escrow.status == "released"
    assert project_row is not None
    assert project_row.status == "delivered"

    earnings_after_project = await client.get(
        f"/v1/orgs/{org['id']}/financials/earnings",
        headers=auth(owner_token),
    )
    assert earnings_after_project.status_code == 200
    assert earnings_after_project.json() == {
        "currency": "USD",
        "gross_revenue": "1999.00",
        "pending_clearance": "1500.00",
        "available_balance": "324.15",
        "commission_rate": "0.15",
        "minimum_payout": "50.00",
    }
