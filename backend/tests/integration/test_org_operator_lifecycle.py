"""End-to-end lifecycle test for organizations as Operators.

Exercises the real org-operator backend flow across capability activation,
org payment-method setup, org Framework purchase and shared-library access,
and the org Project money path. External provider calls and S3 reads are
mocked; application state changes run through the shipped HTTP routes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.modules.financials.models import Escrow, Transaction
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    LicenseGrant,
    Review,
)
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.modules.organizations import billing_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgTeam,
    OrgTeamMember,
)
from app.modules.projects import milestone_service
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
)
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.modules.workspace.models import WorkspaceMessage, WorkspaceUploadSession
from app.shared.models.audit_log import AuditLog
from tests.integration.test_financials_payment_methods import FakeRedis
from tests.integration.test_org_proposal_endpoints import _project_payload
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    create_org,
    migrated_database,
)
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio
__all__ = ["migrated_database"]


class FakeStripeCustomer:
    """Small stand-in for a Stripe customer result."""

    def __init__(self, customer_id: str) -> None:
        """Store the provider customer id."""
        self.id = customer_id


class FakeStripeSetupIntent:
    """Small stand-in for a Stripe SetupIntent result."""

    def __init__(self, setup_intent_id: str, client_secret: str) -> None:
        """Store the setup intent id and client secret."""
        self.id = setup_intent_id
        self.client_secret = client_secret


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store the provider intent id and browser client secret."""
        self.id = payment_intent_id
        self.client_secret = client_secret


class FakeInvoiceTask:
    """Celery task double that records invoice generation requests."""

    def __init__(self) -> None:
        """Initialise the in-memory dispatch log."""
        self.dispatched: list[str] = []

    def delay(self, transaction_id: str) -> None:
        """Record the transaction id that would be sent to Celery."""
        self.dispatched.append(transaction_id)


class FakeDownloadStorage:
    """S3 storage double for library downloads."""

    def __init__(self) -> None:
        """Create empty presigned-get capture state."""
        self.presigned_get_requests: list[tuple[str, str, int]] = []

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a deterministic download URL and capture the request."""
        self.presigned_get_requests.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}?expires={expires_in}"


@pytest.fixture
async def org_operator_lifecycle_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset org-operator rows and patch provider/storage edges."""
    from app.integrations import s3

    fake_redis = FakeRedis()
    fake_storage = FakeDownloadStorage()
    payment_intent_calls: list[dict[str, Any]] = []
    webhook_state: dict[str, Any] = {"event": None}

    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-operator rows in dependency order."""
        async with async_session_factory() as session:
            await session.execute(delete(WebhookEvent))
            await session.execute(delete(AuditLog))
            await session.execute(delete(WorkspaceMessage))
            await session.execute(delete(WorkspaceUploadSession))
            await session.execute(delete(Dispute))
            await session.execute(delete(Deliverable))
            await session.execute(delete(Milestone))
            await session.execute(delete(Escrow))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(Review))
            await session.execute(delete(LicenseGrant))
            await session.execute(delete(License))
            await session.execute(delete(Transaction))
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(ArtifactRarityAudit))
            await session.execute(delete(ArtifactPiiAudit))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(Proposal))
            await session.execute(delete(Project))
            await session.execute(delete(OrgTeamMember))
            await session.execute(delete(OrgTeam))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Return a stable org Stripe customer id."""
        del email, name, idempotency_key
        return FakeStripeCustomer("cus_org_lifecycle")

    async def fake_create_setup_intent(
        *,
        customer_id: str,
    ) -> FakeStripeSetupIntent:
        """Return a stable setup intent for org payment-method setup."""
        assert customer_id == "cus_org_lifecycle"
        return FakeStripeSetupIntent("seti_org_lifecycle", "seti_org_secret")

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        """Capture purchase/funding charge requests and return a client secret."""
        del idempotency_key
        payment_intent_calls.append(
            {
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
            }
        )
        kind = metadata.get("kind", "milestone")
        return FakeStripePaymentIntent(
            f"pi_{kind}_{len(payment_intent_calls)}",
            f"pi_{kind}_secret_{len(payment_intent_calls)}",
        )

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Return the configured webhook event for a valid test signature."""
        del payload
        if signature_header != "valid-signature":
            from app.integrations.stripe import StripeProviderError

            raise StripeProviderError("bad signature")
        event = webhook_state["event"]
        assert isinstance(event, dict)
        return event

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(billing_service.stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(
        billing_service.stripe,
        "create_setup_intent",
        fake_create_setup_intent,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )
    monkeypatch.setattr(
        milestone_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )
    monkeypatch.setattr(webhook_service.stripe, "verify_webhook", fake_verify_webhook)
    monkeypatch.setattr(
        webhook_service,
        "generate_invoice_pdf",
        FakeInvoiceTask(),
        raising=False,
    )
    original_storage = s3.storage
    s3.storage = fake_storage
    try:
        yield {
            "redis": fake_redis,
            "storage": fake_storage,
            "payment_intent_calls": payment_intent_calls,
            "webhook_state": webhook_state,
        }
    finally:
        s3.storage = original_storage
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(
    prefix: str,
    *,
    roles: list[str] | None = None,
    enable_totp: bool = False,
) -> tuple[UUID, str | None]:
    """Create a verified user with optional self roles and TOTP."""
    secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                kyc_status="verified",
                totp_enabled=secret is not None,
                totp_secret=encrypt_totp_secret(secret) if secret else None,
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
            return user.id, secret


async def _create_framework_snapshot(contributor_id: UUID) -> tuple[UUID, UUID]:
    """Create a published Framework plus licensed Artifact snapshot."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Org Operator Lifecycle Framework",
                description="Lifecycle coverage framework.",
                version="1.0.0",
                status="published",
                category="framework",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["org-operator-lifecycle"],
                tags_text="org-operator-lifecycle",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("249.00"),
                currency="USD",
                license_types=["team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            artifact = Artifact(
                framework_id=framework.id,
                name="licensed-playbook.pdf",
                file_key=f"frameworks/{framework.id}/artifacts/licensed-playbook.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="processed",
                current_for_framework=True,
            )
            session.add(artifact)
            await session.flush()
            version = FrameworkVersion(
                framework_id=framework.id,
                version="1.0.0",
                change_type="major",
                change_log="Initial snapshot for lifecycle coverage.",
            )
            session.add(version)
            await session.flush()
            session.add(
                FrameworkVersionArtifact(
                    framework_version_id=version.id,
                    artifact_id=artifact.id,
                    is_preview=False,
                )
            )
            return framework.id, artifact.id


async def _create_org_team(org_id: str, member_id: UUID) -> UUID:
    """Create one org team and add the member to it."""
    async with async_session_factory() as session:
        async with session.begin():
            team = OrgTeam(org_id=UUID(org_id), name="Licensed Team")
            session.add(team)
            await session.flush()
            session.add(OrgTeamMember(team_id=team.id, member_id=member_id))
            return team.id


async def _finalize_org_milestone_plan(
    client: AsyncClient,
    *,
    project_id: str,
    contributor_token: str,
) -> str:
    """Create and finalize one Milestone plan for the accepted Proposal."""
    milestone = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=auth(contributor_token),
        json={
            "sequence": 1,
            "name": "Implementation",
            "description": "Build the approved model.",
            "budget": "1500.00",
            "currency": "USD",
        },
    )
    assert milestone.status_code == 201
    finalized = await client.post(
        f"/v1/projects/{project_id}/milestones/finalize",
        headers=auth(contributor_token),
    )
    assert finalized.status_code == 200
    return milestone.json()["id"]


async def _complete_org_funding(*, project_id: str, milestone_id: str) -> None:
    """Simulate the funding webhook by holding Escrow for the Milestone."""
    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.scalar(
                select(Transaction).where(
                    Transaction.ref_id == UUID(milestone_id),
                    Transaction.ref_type == "project_milestone",
                )
            )
            assert transaction is not None
            transaction.status = "completed"
            transaction.provider_ref = transaction.provider_ref or "pi_milestone_2"
            escrow = Escrow(
                ref_id=UUID(milestone_id),
                ref_type="project_milestone",
                amount=Decimal("1500.00"),
                currency="USD",
                status="held",
                release_conditions={
                    "kind": "project_milestone",
                    "milestone_id": milestone_id,
                    "project_id": project_id,
                },
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            milestone = await session.get(Milestone, UUID(milestone_id))
            project = await session.get(Project, UUID(project_id))
            assert milestone is not None and project is not None
            milestone.status = "funded"
            milestone.funded_at = datetime.now(UTC)
            milestone.escrow_id = escrow.id
            project.status = "in_progress"


async def _mark_deliverable_scanned(deliverable_id: str) -> None:
    """Mark a Deliverable scan-clean so approval is not blocked."""
    async with async_session_factory() as session:
        async with session.begin():
            deliverable = await session.get(Deliverable, UUID(deliverable_id))
            assert deliverable is not None
            deliverable.scan_status = "visible"


async def test_org_operator_lifecycle_covers_library_and_project_money_path(
    client: AsyncClient,
    migrated_database: None,
    org_operator_lifecycle_context: dict[str, Any],
) -> None:
    """Org operator flow works end-to-end and keeps the individual path intact."""
    del migrated_database
    owner_id, owner_totp_secret = await _create_user(
        "org-operator-owner",
        enable_totp=True,
    )
    team_member_user_id, _ = await _create_user("org-operator-team-member")
    direct_member_user_id, _ = await _create_user("org-operator-direct-member")
    ungranted_user_id, _ = await _create_user("org-operator-ungranted")
    contributor_id, _ = await _create_user(
        "org-operator-contributor",
        roles=["contributor"],
    )
    individual_operator_id, _ = await _create_user(
        "individual-operator-regression",
        roles=["operator"],
    )
    owner_token = create_access_token(owner_id, [])
    contributor_token = create_access_token(contributor_id, ["contributor"])

    org = await create_org(client, owner_token, "org-operator")
    team_member_row = await add_member(str(org["id"]), team_member_user_id, "member")
    direct_member_row = await add_member(
        str(org["id"]), direct_member_user_id, "member"
    )
    await add_member(str(org["id"]), ungranted_user_id, "member")
    team_id = await _create_org_team(str(org["id"]), team_member_row)
    framework_id, artifact_id = await _create_framework_snapshot(contributor_id)

    activated = await client.post(
        f"/v1/orgs/{org['id']}/operator-capability/activate",
        headers=auth(owner_token),
    )
    assert activated.status_code == 200
    assert activated.json()["capability"] == "operator"
    assert activated.json()["status"] == "active"

    setup = await client.post(
        f"/v1/orgs/{org['id']}/financials/payment-methods/setup",
        headers=auth(owner_token),
        json={"totp_code": pyotp.TOTP(owner_totp_secret).now()},
    )
    assert setup.status_code == 200
    assert setup.json()["client_secret"] == "seti_org_secret"

    purchase = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/purchase",
        headers=auth(owner_token),
        json={"license_type": "team"},
    )
    assert purchase.status_code == 200
    purchase_body = purchase.json()
    purchase_txn_id = purchase_body["transaction_id"]

    org_operator_lifecycle_context["webhook_state"]["event"] = {
        "id": "evt_org_operator_purchase",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_purchase_1",
                "metadata": {
                    "transaction_id": purchase_txn_id,
                    "kind": "purchase",
                    "framework_id": str(framework_id),
                    "license_type": "team",
                    "payer_org_id": str(org["id"]),
                },
            }
        },
    }
    webhook = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    assert webhook.status_code == 200

    async with async_session_factory() as session:
        license_row = await session.scalar(
            select(License).where(
                License.framework_id == framework_id,
                License.licensee_org_id == UUID(str(org["id"])),
            )
        )
    assert license_row is not None

    team_grant = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_row.id}/grants",
        headers=auth(owner_token),
        json={"team_id": str(team_id)},
    )
    direct_grant = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_row.id}/grants",
        headers=auth(owner_token),
        json={"member_id": str(direct_member_row)},
    )
    assert team_grant.status_code == 201
    assert direct_grant.status_code == 201
    direct_grant_id = direct_grant.json()["id"]

    team_library = await client.get(
        f"/v1/orgs/{org['id']}/library",
        headers=auth(create_access_token(team_member_user_id, [])),
    )
    assert team_library.status_code == 200
    assert team_library.json()["items"][0]["license_id"] == str(license_row.id)

    granted_download = await client.post(
        f"/v1/orgs/{org['id']}/library/{license_row.id}/artifacts/{artifact_id}/download",
        headers=auth(create_access_token(direct_member_user_id, [])),
    )
    ungranted_download = await client.post(
        f"/v1/orgs/{org['id']}/library/{license_row.id}/artifacts/{artifact_id}/download",
        headers=auth(create_access_token(ungranted_user_id, [])),
    )
    assert granted_download.status_code == 200
    assert ungranted_download.status_code == 403

    async with async_session_factory() as session:
        download_row = await session.scalar(
            select(ArtifactDownload).where(
                ArtifactDownload.license_id == license_row.id
            )
        )
    assert download_row is not None
    assert download_row.user_id == direct_member_user_id

    revoked = await client.delete(
        f"/v1/orgs/{org['id']}/licenses/{license_row.id}/grants/{direct_grant_id}",
        headers=auth(owner_token),
    )
    assert revoked.status_code == 204
    revoked_download = await client.post(
        f"/v1/orgs/{org['id']}/library/{license_row.id}/artifacts/{artifact_id}/download",
        headers=auth(create_access_token(direct_member_user_id, [])),
    )
    assert revoked_download.status_code == 403

    created_project = await client.post(
        f"/v1/orgs/{org['id']}/projects",
        headers=auth(owner_token),
        json=_project_payload(),
    )
    assert created_project.status_code == 201
    project_id = created_project.json()["id"]

    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=auth(contributor_token),
        json={
            "scope": "I will deliver the procurement model and rollout plan.",
            "budget": "1500.00",
            "currency": "USD",
            "timeline_days": 21,
            "deliverables": [
                {"name": "Operating model", "description": "Documented model"}
            ],
        },
    )
    assert proposed.status_code == 201
    proposal_id = proposed.json()["id"]

    accepted = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=auth(owner_token),
    )
    assert accepted.status_code == 200
    milestone_id = await _finalize_org_milestone_plan(
        client,
        project_id=project_id,
        contributor_token=contributor_token,
    )

    funded = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=auth(owner_token),
    )
    assert funded.status_code == 200
    assert funded.json()["client_secret"]
    assert (
        org_operator_lifecycle_context["payment_intent_calls"][1]["metadata"][
            "payer_org_id"
        ]
        == str(org["id"])
    )

    async with async_session_factory() as session:
        funding_txn = await session.scalar(
            select(Transaction).where(
                Transaction.ref_id == UUID(milestone_id),
                Transaction.ref_type == "project_milestone",
            )
        )
    assert funding_txn is not None
    assert funding_txn.payer_id is None
    assert funding_txn.payer_org_id == UUID(str(org["id"]))

    await _complete_org_funding(project_id=project_id, milestone_id=milestone_id)

    submitted = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables",
        headers=auth(contributor_token),
        json={
            "name": "Final playbook",
            "description": "Implementation playbook.",
            "file_keys": ["workspace/project/final.pdf"],
        },
    )
    assert submitted.status_code == 201
    deliverable_id = submitted.json()["id"]
    await _mark_deliverable_scanned(deliverable_id)

    approved = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/deliverables/{deliverable_id}/approve",
        headers=auth(owner_token),
    )
    assert approved.status_code == 200

    async with async_session_factory() as session:
        escrow = await session.scalar(
            select(Escrow).where(Escrow.ref_id == UUID(milestone_id))
        )
        released_txn = await session.scalar(
            select(Transaction).where(
                Transaction.ref_id == UUID(milestone_id),
                Transaction.ref_type == "project_milestone",
            )
        )
    assert escrow is not None
    assert escrow.status == "released"
    assert released_txn is not None
    assert released_txn.payee_id == contributor_id
    assert released_txn.payer_org_id == UUID(str(org["id"]))

    individual_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(individual_operator_id, ["operator"])),
        json=_project_payload(),
    )
    assert individual_project.status_code == 201
    assert individual_project.json()["operator_id"] == str(individual_operator_id)
    assert individual_project.json()["operator_org_id"] is None
