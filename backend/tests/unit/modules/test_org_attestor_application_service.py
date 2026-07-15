"""Unit tests for the org attestor application (org-side) service.

Covers the draft → submit lifecycle, owner-signed undertakings (TOTP-gated),
tax-document and payout gates, trial-member nomination (NDA-gated), and the
per-gate checklist derived from a single application row. Enforces the
application flow of docs/superpowers/specs/2026-07-04-org-attestor-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import encrypt_totp_secret, hash_password
from app.main import app
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestorTrial,
    AttestorTrialAnswerKey,
)
from app.modules.auth.models import User
from app.modules.financials.models import PayoutAccount
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations import attestor_application_service as svc
from app.modules.organizations import nda_service
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from app.modules.organizations.schemas import (
    OrgAttestorApplicationCreateRequest,
    OrgAttestorApplicationUpdateRequest,
    OrgAttestorIncorporationDocumentRequest,
    OrgAttestorTaxDocumentRequest,
    OrgUndertakingsSignRequest,
)
from tests.integration.test_auth_sessions import FakeRedis
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _stub_trial_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop trial-nomination tests from enqueuing to the real Celery broker.

    `nominate_trial_member` fires `dispatch_project_notification.delay`, which
    would otherwise land on the shared dev broker and be consumed by a running
    worker against a database that lacks the test user. Tests that assert on the
    dispatch replace this stub with their own capturing double.
    """

    class _NoDispatch:
        def delay(self, **kwargs: object) -> None:
            return None

    monkeypatch.setattr(svc, "dispatch_project_notification", _NoDispatch())


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current database schema exists for the service tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def app_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset org attestor, payout, and identity rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK order before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(AttestorTrialAnswerKey))
            await session.execute(delete(AttestorTrial))
            await session.execute(delete(OrgAttestorApplication))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Organization))
            await session.execute(delete(Framework))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_org(
    *,
    attestor_status: str | None = None,
    totp: bool = False,
) -> tuple[UUID, OwnerFixture]:
    """Create user + org + owner member; return (org_id, owner fixture)."""
    suffix = uuid4().hex[:8]
    secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"orgatt-{suffix}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=f"orgatt-{suffix}",
                email_verified=True,
                totp_enabled=totp,
                totp_secret=encrypt_totp_secret(secret) if totp else None,
            )
            session.add(user)
            await session.flush()
            org = Organization(
                slug=f"orgatt-{suffix}",
                name="Org Attestor Test",
                country="US",
                created_by=user.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
            session.add(member)
            await session.flush()
            if attestor_status is not None:
                session.add(
                    OrgCapability(
                        org_id=org.id,
                        capability="attestor",
                        status=attestor_status,
                    )
                )
            return org.id, OwnerFixture(
                user_id=user.id, member_id=member.id, totp_secret=secret
            )


class OwnerFixture:
    """Test fixture carrying the owner's ids and TOTP secret."""

    def __init__(self, *, user_id: UUID, member_id: UUID, totp_secret: str) -> None:
        self.user_id = user_id
        self.member_id = member_id
        self.totp_secret = totp_secret


def _valid_create() -> OrgAttestorApplicationCreateRequest:
    """Return a complete, valid create request payload."""
    return OrgAttestorApplicationCreateRequest(
        legal_name="Acme Attestations Ltd",
        registration_number="RC123456",
        sectors=["private_equity"],
        functions=["compliance"],
        jurisdictions=["united_states"],
        credentials_summary="Two decades of PE compliance attestation experience.",
        sample_work={"portfolio": "https://example.com/samples"},
        professional_references="Jane Roe, MD of Example Capital.",
    )


async def _add_incorporation_doc(org_id: UUID, actor_id: UUID) -> str:
    """Attach one incorporation document via the service and return its key.

    Incorporation docs are no longer supplied on create; they are appended
    through the dedicated upload endpoint, so submit-success paths must stamp
    one this way first.
    """
    async with async_session_factory() as session:
        session_result = await svc.add_incorporation_document(
            session,
            org_id=org_id,
            actor_id=actor_id,
            payload=OrgAttestorIncorporationDocumentRequest(
                file_name="cert.pdf",
                content_type="application/pdf",
                size_bytes=1024,
            ),
        )
    return session_result.s3_key


async def _load_user(user_id: UUID) -> User:
    """Load a User row by id for TOTP-dependent service calls."""
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        return user


async def _create_calibration_fixture(
    *, omit_last_key: bool, omit_artifacts: bool = False
) -> Framework:
    """Create one calibration fixture, optionally omitting a key row or artifacts."""
    _, owner = await _create_org()
    async with async_session_factory() as session:
        async with session.begin():
            dimensions = (
                await session.scalars(
                    select(AttestationRubricDimension)
                    .where(
                        AttestationRubricDimension.review_type == "quality",
                        AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                    )
                    .order_by(AttestationRubricDimension.display_order.asc())
                )
            ).all()
            assert dimensions

            framework = Framework(
                id=uuid4(),
                contributor_id=owner.user_id,
                title="Calibration Fixture",
                description="Calibration framework fixture.",
                version="1.0.0",
                status="published",
                is_calibration=True,
                calibration_review_type="quality",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk"],
                tags_text="risk",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
            )
            session.add(framework)
            await session.flush()

            if not omit_artifacts:
                session.add(
                    Artifact(
                        framework_id=framework.id,
                        name="Fixture.pdf",
                        file_key="calibration/fixture.pdf",
                        file_size=1024,
                        mime_type="application/pdf",
                        scan_status="clean",
                    )
                )

            keyed_dimensions = dimensions[:-1] if omit_last_key else dimensions
            for dimension in keyed_dimensions:
                session.add(
                    AttestorTrialAnswerKey(
                        framework_id=framework.id,
                        dimension_id=dimension.id,
                        expected_score=4,
                        tolerance=0,
                    )
                )
            await session.flush()
            return framework


@pytest.fixture
async def calibration_fixture(app_state: None) -> Framework:
    """Create one calibration fixture with a complete answer key."""
    del app_state
    return await _create_calibration_fixture(omit_last_key=False)


@pytest.fixture
async def fixture_missing_key(app_state: None) -> Framework:
    """Create one calibration fixture missing an answer-key row."""
    del app_state
    return await _create_calibration_fixture(omit_last_key=True)


@pytest.fixture
async def fixture_missing_artifacts(app_state: None) -> Framework:
    """Create one calibration fixture with a complete key but no artifacts."""
    del app_state
    return await _create_calibration_fixture(omit_last_key=False, omit_artifacts=True)


async def test_create_rejects_second_live_application(app_state: None) -> None:
    """A second live application for the same org raises 409."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.create_application(
                session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
            )
    assert exc.value.status_code == 409


async def test_update_after_submit_rejected(app_state: None) -> None:
    """Editing an application already submitted raises 409."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    await _add_incorporation_doc(org_id, owner.user_id)
    async with async_session_factory() as session:
        await svc.submit_application(session, org_id=org_id, actor_id=owner.user_id)
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.update_application(
                session,
                org_id=org_id,
                actor_id=owner.user_id,
                payload=OrgAttestorApplicationUpdateRequest(legal_name="New Name Ltd"),
            )
    assert exc.value.status_code == 409


async def test_submit_incomplete_kyb_rejected(app_state: None) -> None:
    """Submitting without KYB fields raises 422."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        payload = _valid_create()
        payload.legal_name = None
        payload.registration_number = None
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=payload
        )
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.submit_application(
                session, org_id=org_id, actor_id=owner.user_id
            )
    assert exc.value.status_code == 422


async def test_add_incorporation_document_appends_key(app_state: None) -> None:
    """Uploading an incorporation document appends its key to the application."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    key = await _add_incorporation_doc(org_id, owner.user_id)
    async with async_session_factory() as session:
        application = await session.scalar(
            select(OrgAttestorApplication).where(
                OrgAttestorApplication.org_id == org_id
            )
        )
    assert application is not None
    assert application.incorporation_doc_keys == [key]


async def test_remove_incorporation_document_detaches_key(app_state: None) -> None:
    """Removing an incorporation document drops just that key from the list."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    key = await _add_incorporation_doc(org_id, owner.user_id)
    async with async_session_factory() as session:
        application = await svc.remove_incorporation_document(
            session, org_id=org_id, actor_id=owner.user_id, s3_key=key
        )
    assert application.incorporation_doc_keys == []


async def test_remove_incorporation_document_unknown_key_rejected(
    app_state: None,
) -> None:
    """Removing a key not attached to the application raises 404."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.remove_incorporation_document(
                session, org_id=org_id, actor_id=owner.user_id, s3_key="nope/x.pdf"
            )
    assert exc.value.status_code == 404


async def test_submit_succeeds_with_full_kyb(app_state: None) -> None:
    """A complete application with an incorporation document submits cleanly."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    await _add_incorporation_doc(org_id, owner.user_id)
    async with async_session_factory() as session:
        application = await svc.submit_application(
            session, org_id=org_id, actor_id=owner.user_id
        )
    assert application.status == "submitted"


async def test_needs_info_notifies_org_owner(
    app_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sending an application back for info notifies the org owner.

    The owner manages the application, so returning it to needs_info must
    queue a durable notification to the owner's user, deep linking the
    attestor application page so they can act on the feedback.
    """
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    await _add_incorporation_doc(org_id, owner.user_id)
    async with async_session_factory() as session:
        await svc.submit_application(session, org_id=org_id, actor_id=owner.user_id)

    calls: list[dict[str, object]] = []

    class _FakeTask:
        def delay(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(svc, "dispatch_project_notification", _FakeTask())

    async with async_session_factory() as session:
        application_id = await session.scalar(
            select(OrgAttestorApplication.id).where(
                OrgAttestorApplication.org_id == org_id
            )
        )
    assert application_id is not None
    async with async_session_factory() as session:
        await svc.admin_needs_info(
            session,
            application_id=application_id,
            admin_id=owner.user_id,
            feedback="Please link a payout account.",
        )

    assert len(calls) == 1
    assert calls[0]["user_id"] == str(owner.user_id)
    assert calls[0]["notification_type"] == "org_attestor_needs_info"
    assert str(org_id) in str(calls[0]["link"])


async def test_sign_undertakings_wrong_totp_rejected(app_state: None) -> None:
    """Signing undertakings with an invalid TOTP code raises 422."""
    org_id, owner = await _create_org(attestor_status="pending", totp=True)
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    user = await _load_user(owner.user_id)
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.sign_undertakings(
                session,
                FakeRedis(),
                org_id=org_id,
                user=user,
                payload=OrgUndertakingsSignRequest(
                    declarations=[],
                    accept_policy=True,
                    accept_confidentiality=True,
                    totp_code="000000",
                ),
            )
    assert exc.value.status_code == 422


async def test_nominate_unsigned_member_rejected(app_state: None) -> None:
    """Nominating a member without a current NDA signature raises 422."""
    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.nominate_trial_member(
                session,
                org_id=org_id,
                actor_id=owner.user_id,
                member_id=owner.member_id,
            )
    assert exc.value.status_code == 422
    assert exc.value.detail == {"error_code": "nda_required"}


async def test_nominate_signed_member_succeeds(app_state: None) -> None:
    """Nominating an NDA-signed member stamps the trial member."""
    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        await nda_service.sign_nda(session, org_id=org_id, user_id=owner.user_id)
    async with async_session_factory() as session:
        application = await svc.nominate_trial_member(
            session, org_id=org_id, actor_id=owner.user_id, member_id=owner.member_id
        )
    assert application.trial_member_id == owner.member_id


async def test_nominate_notifies_member(
    app_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nominating a trial member queues an in-app + email notification to them.

    The nominee must be told they were selected, so the service dispatches a
    durable notification (in-app + email fanout) to the member's user, deep
    linking the org attestor page.
    """
    org_id, owner = await _create_org(attestor_status="pending")
    calls: list[dict[str, object]] = []

    class _FakeTask:
        def delay(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(svc, "dispatch_project_notification", _FakeTask())

    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        await nda_service.sign_nda(session, org_id=org_id, user_id=owner.user_id)
    async with async_session_factory() as session:
        await svc.nominate_trial_member(
            session, org_id=org_id, actor_id=owner.user_id, member_id=owner.member_id
        )

    assert len(calls) == 1
    assert calls[0]["user_id"] == str(owner.user_id)
    assert calls[0]["notification_type"] == "org_attestor_trial_nominated"
    assert str(org_id) in str(calls[0]["link"])


async def test_gate_checklist_reflects_service_stamps(app_state: None) -> None:
    """Signing undertakings, linking payout, and setting tax flip their gates."""
    org_id, owner = await _create_org(attestor_status="pending", totp=True)
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        _, checklist = await svc.get_application(session, org_id=org_id)
    assert checklist.undertakings_signed is False
    assert checklist.payout_account_linked is False
    assert checklist.tax_document_uploaded is False

    user = await _load_user(owner.user_id)
    code = pyotp.TOTP(owner.totp_secret).now()
    async with async_session_factory() as session:
        await svc.sign_undertakings(
            session,
            FakeRedis(),
            org_id=org_id,
            user=user,
            payload=OrgUndertakingsSignRequest(
                declarations=[],
                accept_policy=True,
                accept_confidentiality=True,
                totp_code=code,
            ),
        )

    # Link an org-owned payout account through the partial update path.
    async with async_session_factory() as session:
        account = PayoutAccount(
            org_id=org_id,
            provider="stripe",
            provider_account_id=f"acct_{uuid4().hex[:12]}",
            provider_account_lookup_hash=uuid4().hex + uuid4().hex,
            account_type="express",
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        account_id = account.id
    async with async_session_factory() as session:
        await svc.update_application(
            session,
            org_id=org_id,
            actor_id=owner.user_id,
            payload=OrgAttestorApplicationUpdateRequest(payout_account_id=account_id),
        )

    async with async_session_factory() as session:
        await svc.set_tax_document(
            session,
            org_id=org_id,
            actor_id=owner.user_id,
            payload=OrgAttestorTaxDocumentRequest(
                tax_document_type="w9",
                file_name="w9.pdf",
                content_type="application/pdf",
                size_bytes=1024,
            ),
        )

    async with async_session_factory() as session:
        _, checklist = await svc.get_application(session, org_id=org_id)
    assert checklist.undertakings_signed is True
    assert checklist.payout_account_linked is True
    assert checklist.tax_document_uploaded is True


async def test_gate_checklist_reflects_admin_and_trial_stamps(app_state: None) -> None:
    """KYB verification, review, and a passed trial flip their gates."""
    from datetime import UTC, datetime

    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        application = await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        application_id = application.id

    now = datetime.now(UTC)
    async with async_session_factory() as session:
        row = await session.get(OrgAttestorApplication, application_id)
        assert row is not None
        row.kyb_verified_at = now
        row.reviewed_at = now
        row.status = "submitted"
        session.add(
            AttestorTrial(
                org_application_id=application_id,
                org_id=org_id,
                member_id=owner.member_id,
                status="passed",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        _, checklist = await svc.get_application(session, org_id=org_id)
    assert checklist.kyb_verified is True
    assert checklist.credentials_reviewed is True
    assert checklist.trial_passed is True


async def test_admin_start_trial_notifies_member(
    app_state: None,
    calibration_fixture: Framework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting the trial queues an in-app + email notification to the nominee.

    Nomination only stamps the member; the trial becomes actionable when a
    platform admin starts it. The nominee must be told at that moment, so
    ``admin_start_trial`` dispatches a durable notification deep-linking the
    org attestor page.
    """
    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        application = await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        application_id = application.id
    async with async_session_factory() as session:
        row = await session.get(OrgAttestorApplication, application_id)
        assert row is not None
        row.status = "submitted"
        row.trial_member_id = owner.member_id
        await session.commit()

    calls: list[dict[str, object]] = []

    class _FakeTask:
        def delay(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(svc, "dispatch_project_notification", _FakeTask())

    async with async_session_factory() as session:
        await svc.admin_start_trial(
            session,
            application_id=application_id,
            admin_id=owner.user_id,
            framework_id=calibration_fixture.id,
        )

    assert len(calls) == 1
    assert calls[0]["user_id"] == str(owner.user_id)
    assert calls[0]["notification_type"] == "org_attestor_trial_assigned"
    assert str(org_id) in str(calls[0]["link"])


async def test_admin_start_trial_sets_seeded_framework(
    calibration_fixture: Framework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting the trial with a valid fixture stamps seeded_framework_id."""
    application_id, _, admin_id = await _submitted_app_with_nominee(monkeypatch)
    async with async_session_factory() as session:
        trial = await svc.admin_start_trial(
            session,
            application_id=application_id,
            admin_id=admin_id,
            framework_id=calibration_fixture.id,
        )

    assert trial.seeded_framework_id == calibration_fixture.id
    assert trial.status == "assigned"


async def test_admin_start_trial_rejects_incomplete_key(
    fixture_missing_key: Framework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fixture missing a key row for its rubric is rejected with 422."""
    application_id, _, admin_id = await _submitted_app_with_nominee(monkeypatch)
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.admin_start_trial(
                session,
                application_id=application_id,
                admin_id=admin_id,
                framework_id=fixture_missing_key.id,
            )

    assert exc.value.status_code == 422


async def test_admin_start_trial_rejects_fixture_without_artifacts(
    fixture_missing_artifacts: Framework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fixture with a complete key but no artifacts is rejected with 422."""
    application_id, _, admin_id = await _submitted_app_with_nominee(monkeypatch)
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.admin_start_trial(
                session,
                application_id=application_id,
                admin_id=admin_id,
                framework_id=fixture_missing_artifacts.id,
            )

    assert exc.value.status_code == 422


async def _submitted_app_with_nominee(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[UUID, UUID, UUID]:
    """Seed a submitted application with a nominated trial member.

    Silences the notification dispatch so tests exercise only the trial
    state machine. Returns (application_id, member_id, admin_user_id).
    """
    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        application = await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        application_id = application.id
    async with async_session_factory() as session:
        row = await session.get(OrgAttestorApplication, application_id)
        assert row is not None
        row.status = "submitted"
        row.trial_member_id = owner.member_id

        await session.commit()

    class _FakeTask:
        def delay(self, **kwargs: object) -> None:
            return None

    monkeypatch.setattr(svc, "dispatch_project_notification", _FakeTask())
    return application_id, owner.member_id, owner.user_id


async def test_admin_start_trial_is_idempotent_while_assigned(
    app_state: None,
    calibration_fixture: Framework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting the trial twice must not stack a second assigned trial.

    A double-click (or a UI that re-enables the button) previously inserted a
    fresh AttestorTrial per call, marching ``attempt`` past its check
    constraint. While a trial is already ``assigned`` the second call is a
    no-op returning the existing trial.
    """
    application_id, _, admin_id = await _submitted_app_with_nominee(monkeypatch)
    async with async_session_factory() as session:
        first = await svc.admin_start_trial(
            session,
            application_id=application_id,
            admin_id=admin_id,
            framework_id=calibration_fixture.id,
        )
        first_id = first.id
    async with async_session_factory() as session:
        second = await svc.admin_start_trial(
            session,
            application_id=application_id,
            admin_id=admin_id,
            framework_id=calibration_fixture.id,
        )
        assert second.id == first_id
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(AttestorTrial).where(
                    AttestorTrial.org_application_id == application_id
                )
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].attempt == 1


async def test_admin_start_trial_retries_after_failure(
    app_state: None,
    calibration_fixture: Framework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed first attempt allows a second, with attempt incremented."""
    application_id, member_id, admin_id = await _submitted_app_with_nominee(monkeypatch)
    async with async_session_factory() as session:
        row = await session.get(OrgAttestorApplication, application_id)
        assert row is not None
        session.add(
            AttestorTrial(
                org_application_id=application_id,
                org_id=row.org_id,
                member_id=member_id,
                status="failed",
                attempt=1,
            )
        )
        await session.commit()
    async with async_session_factory() as session:
        retry = await svc.admin_start_trial(
            session,
            application_id=application_id,
            admin_id=admin_id,
            framework_id=calibration_fixture.id,
        )
        assert retry.attempt == 2
        assert retry.status == "assigned"


async def test_admin_start_trial_caps_attempts_at_two(
    app_state: None,
    calibration_fixture: Framework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second failed attempt is terminal — no third trial, a clean 422.

    The check constraint caps ``attempt`` at 2; the service must reject the
    third start with a typed error instead of an IntegrityError.
    """
    application_id, member_id, admin_id = await _submitted_app_with_nominee(monkeypatch)
    async with async_session_factory() as session:
        row = await session.get(OrgAttestorApplication, application_id)
        assert row is not None
        session.add(
            AttestorTrial(
                org_application_id=application_id,
                org_id=row.org_id,
                member_id=member_id,
                status="failed",
                attempt=2,
            )
        )
        await session.commit()
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.admin_start_trial(
                session,
                application_id=application_id,
                admin_id=admin_id,
                framework_id=calibration_fixture.id,
            )
    assert exc.value.status_code == 422


async def test_admin_start_trial_rejects_when_already_passed(
    app_state: None,
    calibration_fixture: Framework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once a trial has passed, starting again is a 409 conflict."""
    application_id, member_id, admin_id = await _submitted_app_with_nominee(monkeypatch)
    async with async_session_factory() as session:
        row = await session.get(OrgAttestorApplication, application_id)
        assert row is not None
        session.add(
            AttestorTrial(
                org_application_id=application_id,
                org_id=row.org_id,
                member_id=member_id,
                status="passed",
                attempt=1,
            )
        )
        await session.commit()
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.admin_start_trial(
                session,
                application_id=application_id,
                admin_id=admin_id,
                framework_id=calibration_fixture.id,
            )
    assert exc.value.status_code == 409


@pytest.mark.parametrize(
    "notification_type",
    [
        "org_attestor_trial_nominated",
        "org_attestor_trial_assigned",
        "org_attestor_needs_info",
    ],
)
async def test_trial_notification_types_persist(
    app_state: None, notification_type: str
) -> None:
    """The org attestor notification types must be storable durable rows.

    ``dispatch_project_notification`` persists an in-app row typed by the
    ``notification_type_enum``. Each type must be a valid member of that enum,
    or the worker insert fails and the recipient is never told.
    """
    from app.modules.notifications import service as notification_service

    _, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        async with session.begin():
            notification = await notification_service.create_notification(
                db=session,
                user_id=owner.user_id,
                notification_type=notification_type,
                title="Trial",
                body="Trial body.",
                link="/dashboard",
                payload=None,
                dedupe_key=None,
            )
    assert notification is not None
    assert notification.notification_type == notification_type


async def test_admin_list_documents_returns_presigned_links(
    app_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Admin document review returns one presigned GET link per KYB + tax doc.

    KYB and tax documents live in the private bucket, so the admin panel can
    only surface them through short-lived presigned GET URLs generated on
    demand. One link is produced per incorporation document and one for the
    tax document, each labelled and carrying the original file name.
    """
    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        application = await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        application_id = application.id
    await _add_incorporation_doc(org_id, owner.user_id)
    async with async_session_factory() as session:
        await svc.set_tax_document(
            session,
            org_id=org_id,
            actor_id=owner.user_id,
            payload=OrgAttestorTaxDocumentRequest(
                tax_document_type="w9",
                file_name="w9.pdf",
                content_type="application/pdf",
                size_bytes=1024,
            ),
        )

    captured: list[tuple[str, str | None]] = []

    def _fake_presigned_get(
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        captured.append((key, download_name))
        return f"https://signed.example/{key}"

    monkeypatch.setattr(svc.s3.storage, "presigned_get", _fake_presigned_get)
    monkeypatch.setattr(svc.s3.storage, "object_exists", lambda bucket, key: True)

    async with async_session_factory() as session:
        documents = await svc.admin_list_documents(
            session, application_id=application_id, admin_id=owner.user_id
        )

    assert len(documents) == 2
    labels = [doc.label for doc in documents]
    assert any("Incorporation" in label for label in labels)
    assert any("Tax" in label for label in labels)
    filenames = [doc.filename for doc in documents]
    assert "cert.pdf" in filenames
    assert "w9.pdf" in filenames
    assert all(doc.available for doc in documents)
    assert all(doc.url.startswith("https://signed.example/") for doc in documents)


async def test_admin_list_documents_flags_missing_object(
    app_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reserved key with no uploaded object is flagged unavailable, not signed.

    Signing a GET for a missing object yields an S3 ``NoSuchKey`` page, so the
    link is returned with ``available=False`` and an empty URL instead.
    """
    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        application = await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        application_id = application.id
    await _add_incorporation_doc(org_id, owner.user_id)

    def _boom_presigned_get(*args: object, **kwargs: object) -> str:
        raise AssertionError("must not sign a GET for a missing object")

    monkeypatch.setattr(svc.s3.storage, "presigned_get", _boom_presigned_get)
    monkeypatch.setattr(svc.s3.storage, "object_exists", lambda bucket, key: False)

    async with async_session_factory() as session:
        documents = await svc.admin_list_documents(
            session, application_id=application_id, admin_id=owner.user_id
        )

    assert len(documents) == 1
    assert documents[0].available is False
    assert documents[0].url == ""


async def test_admin_list_documents_missing_application(app_state: None) -> None:
    """Listing documents for an unknown application raises 404."""
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.admin_list_documents(
                session, application_id=uuid4(), admin_id=uuid4()
            )
    assert exc.value.status_code == 404


async def test_trial_filter_lists_only_apps_with_a_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 'trial' queue filter returns submitted apps that have a trial."""
    application_id, member_id, _ = await _submitted_app_with_nominee(monkeypatch)

    # No trial yet -> absent from the trial queue.
    async with async_session_factory() as session:
        rows, total = await svc.admin_list_applications(
            session, status_filter="trial", page=1, page_size=10
        )
    assert application_id not in {r.id for r in rows}
    assert total == 0

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                AttestorTrial(
                    org_application_id=application_id,
                    member_id=member_id,
                    status="assigned",
                    attempt=1,
                )
            )

    async with async_session_factory() as session:
        rows, total = await svc.admin_list_applications(
            session, status_filter="trial", page=1, page_size=10
        )
    assert application_id in {r.id for r in rows}
    assert total == 1
