# Attestation Module 2b — Framework Access Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Attestors a secure, read-only access package — exec-summary preview for the matched cohort, full content unlock for the accepting Attestor only, automatic status-derived revocation, and an access-event audit trail — with an owner-consent gate closing the operator-initiated IP hole.

**Architecture:** Additive on merged Module 2a. Operator-initiated requests land in a new `pending_owner_consent` state (unpaid); the framework owner approves (→ `pending_fee`) or declines (→ `cancelled`); the operator then funds via a dedicated endpoint reusing an extracted `_fund_attestation()` helper. Attestor content entitlement is **computed from live status** (no grant table) and every presigned access is logged to a new `attestation_artifact_access` table. Full unlock requires a per-accept content-use acknowledgment recorded on the attestation row.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, PostgreSQL 16, Stripe (escrow), Celery + Beat, pytest + httpx AsyncClient, loguru.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-attestation-module-2b-framework-access-package-design.md`. Source of truth: `docs/Auracles Attestation — Product Development Workflow.md` §2.5 + §3.4.
- Entitlement is **derived from status, never stored**. No grant table. `scope_for`: caller's offer `offered` → `preview`; `attestation.attestor_id == user.id` AND status in `{accepted, report_submitted, disputed}` AND `content_ack_at is not None` → `full`; else `none`.
- Full-access status set is exactly `{accepted, report_submitted, disputed}`. `resolved` is excluded.
- New status value: `pending_owner_consent`. Operator-initiated only; owner-initiated path stays byte-for-byte unchanged.
- Consent-then-fund: operator-initiated requests create **no transaction and no PaymentIntent** until funded. Owner decline/timeout → `cancelled`, zero money moved, no refund path.
- Owner-approve flips status only (no PaymentIntent); operator funds via `POST /v1/attestations/{id}/fund` (payer is the caller, gets `client_secret` synchronously). Stripe has no retrieve method — never store `client_secret`.
- Consent timeout config key: `attestation_owner_consent_hours`, default `72`, minimum `1`.
- File delivery is presigned-only, never proxied. Reuse TTL `ARTIFACT_DOWNLOAD_URL_TTL_SECONDS = 900`. Never log presigned URLs or `client_secret`. No brief contents in logs/audit (IDs/bools only).
- Every artifact access → `attestation_artifact_access` row + audit log. Consent approve/decline audited.
- All inputs Pydantic; RBAC at dependency layer; deny-by-default (non-owner on consent → 404, no existence leak).
- Migration filename `YYYY_MM_DD_description.py`; round-trip (`upgrade head` + `downgrade -1`) must pass. Current head: `2026_06_30_0044`.
- Loguru only (`module="attestation"`), no `print`. Google-style docstrings on every new function/class/module.
- Gates before any task is "done": targeted `pytest`, whole-repo `uv run ruff check .`, `uv run mypy app`. Run from `backend/`. Commit messages end at the last meaningful line — no `Co-Authored-By` trailer. Work on `main`.

---

### Task 1: Schema foundation — migration + models

**Files:**
- Modify: `backend/app/modules/attestation/models.py` (Attestation columns + new `AttestationArtifactAccess`)
- Create: `backend/migrations/versions/2026_06_30_0045_attestation_access_package.py`
- Test: `backend/tests/unit/test_attestation_access_package_migration.py`

**Interfaces:**
- Produces: `Attestation.content_ack_at: Mapped[datetime | None]`, `Attestation.content_ack_version: Mapped[str | None]`; ORM model `AttestationArtifactAccess` (`id, attestation_id, attestor_id, artifact_id, scope, ip_address, created_at`); enum value `pending_owner_consent`; config key `attestation_owner_consent_hours = "72"`.

- [ ] **Step 1: Write the failing migration round-trip test**

Create `backend/tests/unit/test_attestation_access_package_migration.py` (mirror `test_attestation_review_type_migration.py`):

```python
"""Migration coverage for Module 2b access-package schema."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PRIOR_HEAD = "2026_06_30_0044"


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Upgrade to head and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.downgrade(alembic_config, PRIOR_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PRIOR_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_access_package_schema_added(migrated_engine: Engine) -> None:
    """Upgrade adds ack columns, the access table, enum value, and consent config."""
    inspector = inspect(migrated_engine)
    attestation_cols = {c["name"] for c in inspector.get_columns("attestations")}
    tables = set(inspector.get_table_names())
    with migrated_engine.connect() as connection:
        enum_values = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT e.enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'attestation_status_enum'"
                )
            )
        }
        consent_cfg = connection.execute(
            text(
                "SELECT value FROM platform_config "
                "WHERE key = 'attestation_owner_consent_hours'"
            )
        ).scalar_one_or_none()

    assert {"content_ack_at", "content_ack_version"}.issubset(attestation_cols)
    assert "attestation_artifact_access" in tables
    assert "pending_owner_consent" in enum_values
    assert consent_cfg == "72"


def test_downgrade_reverts_access_package() -> None:
    """Downgrade drops ack columns, the access table, and the consent config."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.downgrade(alembic_config, PRIOR_HEAD)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PRIOR_HEAD)
    try:
        inspector = inspect(engine)
        attestation_cols = {c["name"] for c in inspector.get_columns("attestations")}
        tables = set(inspector.get_table_names())
        with engine.connect() as connection:
            consent_cfg = connection.execute(
                text(
                    "SELECT value FROM platform_config "
                    "WHERE key = 'attestation_owner_consent_hours'"
                )
            ).scalar_one_or_none()
        assert "content_ack_at" not in attestation_cols
        assert "content_ack_version" not in attestation_cols
        assert "attestation_artifact_access" not in tables
        assert consent_cfg is None
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_attestation_access_package_migration.py -v`
Expected: FAIL — migration `2026_06_30_0045` does not exist / columns missing.

- [ ] **Step 3: Add the model columns + new model**

In `backend/app/modules/attestation/models.py`, add to `class Attestation` (after the `closed_at` column near line 500):

```python
    content_ack_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    content_ack_version: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Add a new model (place after `class AttestationOffer`):

```python
class AttestationArtifactAccess(Base):
    """Append-only log of every presigned Attestation artifact access.

    Records who accessed which artifact under what entitlement scope. The trail
    is the forensic evidence behind the content-use acknowledgment (FR §2.5).
    """

    __tablename__ = "attestation_artifact_access"
    __table_args__ = (
        Index("idx_attestation_artifact_access_attestation", "attestation_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id"),
        nullable=False,
    )
    attestor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
```

(Confirm `Index`, `ForeignKey`, `text`, `PG_UUID`, `DateTime`, `Text`, `Mapped`, `mapped_column`, `UUID`, `datetime` are already imported in this module — they are used elsewhere in the file. Add the `pending_owner_consent` literal to the `ATTESTATION_STATUS_ENUM` tuple too: insert `"pending_owner_consent",` after `"pending_fee",`.)

- [ ] **Step 4: Write the migration**

Create `backend/migrations/versions/2026_06_30_0045_attestation_access_package.py`:

```python
"""Add Attestation access-package schema: consent state, ack, access log.

Implements Module 2b (workflow-doc §2.5). Adds the pending_owner_consent status
value, per-accept content acknowledgment columns, the attestation_artifact_access
audit table, and the owner-consent timeout config. Additive and backward-compatible.

Revision ID: 2026_06_30_0045
Revises: 2026_06_30_0044
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_30_0045"
down_revision: str | Sequence[str] | None = "2026_06_30_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSENT_HOURS_KEY = "attestation_owner_consent_hours"


def upgrade() -> None:
    """Add consent enum value, ack columns, access table, and consent config."""
    op.execute(
        "ALTER TYPE attestation_status_enum ADD VALUE IF NOT EXISTS "
        "'pending_owner_consent'"
    )
    op.add_column(
        "attestations",
        sa.Column("content_ack_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestations",
        sa.Column("content_ack_version", sa.Text(), nullable=True),
    )
    op.create_table(
        "attestation_artifact_access",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("attestation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attestor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["attestation_id"], ["attestations.id"]),
        sa.ForeignKeyConstraint(["attestor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
    )
    op.create_index(
        "idx_attestation_artifact_access_attestation",
        "attestation_artifact_access",
        ["attestation_id"],
    )
    consent_seed = sa.text(
        "INSERT INTO platform_config (key, value) VALUES (:key, '72') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(consent_seed.bindparams(key=CONSENT_HOURS_KEY))


def downgrade() -> None:
    """Drop access table, ack columns, and consent config (enum value persists)."""
    consent_delete = sa.text("DELETE FROM platform_config WHERE key = :key")
    op.execute(consent_delete.bindparams(key=CONSENT_HOURS_KEY))
    op.drop_index(
        "idx_attestation_artifact_access_attestation",
        table_name="attestation_artifact_access",
    )
    op.drop_table("attestation_artifact_access")
    op.drop_column("attestations", "content_ack_version")
    op.drop_column("attestations", "content_ack_at")
```

Note: `ADD VALUE` cannot run inside a transaction block on some Postgres versions. If `alembic upgrade` errors with "ALTER TYPE ... ADD VALUE cannot run inside a transaction block", split the enum statement into its own migration that sets `op.execute` after committing, or add `op.get_bind().commit()` is not available — instead set the migration-level `transactional_ddl`. Standard fix used in this repo: the 2a migration created the enum fresh; here we extend. If the in-transaction error appears, move ONLY the `ALTER TYPE ... ADD VALUE` into a separate prior migration `2026_06_30_0045a` with `from alembic import context` and run it autocommit via `with op.get_context().autocommit_block():`.

Prefer the autocommit block directly:

```python
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE attestation_status_enum ADD VALUE IF NOT EXISTS "
            "'pending_owner_consent'"
        )
```

Use this `autocommit_block()` form in `upgrade()` for the enum statement.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_attestation_access_package_migration.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/models.py backend/migrations/versions/2026_06_30_0045_attestation_access_package.py backend/tests/unit/test_attestation_access_package_migration.py
git commit -m "feat(attestation): add access-package schema — consent state, ack, access log"
```

---

### Task 2: Operator-initiated → pending_owner_consent + extract `_fund_attestation`

**Files:**
- Modify: `backend/app/modules/attestation/service.py` (`request_attestation`, new helpers)
- Modify: `backend/app/modules/attestation/schemas.py` (new `AttestationConsentPendingResponse`)
- Modify: `backend/app/modules/attestation/router.py` (`POST /attestations` response_model union)
- Modify: `backend/app/modules/attestation/notifications.py` (consent-requested notice)
- Test: `backend/tests/integration/test_attestation_requests.py`

**Interfaces:**
- Consumes: existing `_validate_attestation_target` (returns `initiator_is_owner: bool`), `_attestation_fee`, `_reject_duplicate_in_flight_request`, `stripe.create_payment_intent`, `Transaction`, `write_audit`.
- Produces: `_fund_attestation(db, *, requestor, attestation_id, amount, customer_id) -> AttestationFundingResponse`; `_create_attestation(db, *, requestor_id, payload, amount, initiator_is_owner, status_value) -> UUID` (attestation-only, no transaction); `AttestationConsentPendingResponse(id: UUID, status: str)`; `notify_consent_requested(attestation, *, owner_id)`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_attestation_requests.py`:

```python
async def test_operator_initiated_request_enters_consent_unpaid(
    client, operator_auth, published_framework_owned_by_other, db_session
):
    """An operator request on a non-owned framework lands in pending_owner_consent.

    No PaymentIntent and no transaction are created before owner consent (§2.5).
    """
    resp = await client.post(
        "/v1/attestations",
        headers=operator_auth,
        json={
            "target_type": "framework",
            "target_id": str(published_framework_owned_by_other.id),
            "review_type": "quality",
            "brief": {
                "what_it_does": "x",
                "use_case": "x",
                "jurisdiction": "US",
                "focus_areas": "x",
                "desired_outcome": "x",
            },
            "requested_specializations": ["compliance"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending_owner_consent"
    assert "client_secret" not in body
    txn = await db_session.scalar(
        select(Transaction).where(Transaction.ref_id == UUID(body["id"]))
    )
    assert txn is None
```

(Reuse/extend existing fixtures from this test module: it already builds operator auth and published-framework-owned-by-other for the 2a operator-initiated tests. Reuse those exact fixtures; do not invent new ones if equivalents exist.)

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestation_requests.py::test_operator_initiated_request_enters_consent_unpaid -v`
Expected: FAIL — current code funds immediately (returns `client_secret`, creates transaction).

- [ ] **Step 3: Add schema + notification**

In `schemas.py` add:

```python
class AttestationConsentPendingResponse(BaseModel):
    """Returned for operator-initiated requests awaiting framework-owner consent."""

    id: UUID
    status: str
```

In `notifications.py` add (mirror `notify_request_received_for_owner`):

```python
def notify_consent_requested(attestation: Attestation, *, owner_id: UUID) -> None:
    """Notify a framework owner that consent is required to start an attestation."""
    _dispatch(
        attestation,
        recipient_id=owner_id,
        notification_type="attestation_consent_requested",
        dedupe_suffix="consent",
    )
```

(Match the exact `_dispatch` signature/keywords used by `notify_request_received_for_owner`. If that function passes positional/keyword args differently, copy its shape.)

- [ ] **Step 4: Refactor `request_attestation` + add helpers**

Replace the body of `request_attestation` (service.py:82–200) so it branches on `initiator_is_owner`. Extract the funding tail into `_fund_attestation`, and add attestation-only creation `_create_attestation`. Full replacement:

```python
async def request_attestation(
    db: AsyncSession,
    requestor: User,
    payload: AttestationRequestCreateRequest,
) -> AttestationFundingResponse | AttestationConsentPendingResponse:
    """Create an Attestation request; fund now if owner-initiated, else seek consent.

    Owner-initiated requests fund escrow immediately (Module 2a). Operator-initiated
    requests on a published framework owned by someone else enter pending_owner_consent
    and are not charged until the owner approves and the operator funds (§2.5).

    Returns:
        AttestationFundingResponse for owner-initiated (with client_secret), or
        AttestationConsentPendingResponse for operator-initiated requests.
    """
    requestor_id = requestor.id

    initiator_is_owner = await _validate_attestation_target(
        db=db,
        requestor_id=requestor_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
    )
    if payload.target_type == "framework" and (
        payload.review_type is None or payload.brief is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Framework attestation requires a review type and brief.",
        )
    await _reject_duplicate_in_flight_request(
        db=db,
        requestor_id=requestor_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        review_type=payload.review_type,
    )
    amount = await _attestation_fee(db, payload.target_type, payload.review_type)

    if not initiator_is_owner:
        attestation_id = await _create_attestation(
            db=db,
            requestor_id=requestor_id,
            payload=payload,
            amount=amount,
            initiator_is_owner=False,
            status_value="pending_owner_consent",
        )
        owner_id = await _target_framework_owner_id(db, payload.target_id)
        if owner_id is not None:
            attestation = await db.get(Attestation, attestation_id)
            attestation_notifications.notify_consent_requested(
                attestation, owner_id=owner_id
            )
        logger.bind(
            module="attestation",
            action="request_attestation",
            user_id=requestor_id,
            attestation_id=attestation_id,
        ).info("attestation_consent_requested")
        return AttestationConsentPendingResponse(
            id=attestation_id, status="pending_owner_consent"
        )

    customer_id = await _ensure_stripe_customer(db, requestor)
    attestation_id = await _create_attestation(
        db=db,
        requestor_id=requestor_id,
        payload=payload,
        amount=amount,
        initiator_is_owner=True,
        status_value="pending_fee",
    )
    return await _fund_attestation(
        db=db,
        requestor=requestor,
        attestation_id=attestation_id,
        amount=amount,
        customer_id=customer_id,
    )
```

Add `_ensure_stripe_customer` (extract the existing customer-create try/except from old `request_attestation`):

```python
async def _ensure_stripe_customer(db: AsyncSession, requestor: User) -> str:
    """Return the requestor's Stripe customer id, creating one if absent."""
    if requestor.stripe_customer_id is not None:
        return requestor.stripe_customer_id
    try:
        customer = await stripe.create_customer(
            email=requestor.email,
            name=requestor.display_name,
            idempotency_key=f"stripe_customer:{requestor.id}",
        )
    except StripeProviderError as exc:
        logger.bind(
            module="attestation", action="request_attestation", user_id=requestor.id
        ).error("stripe_customer_create_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc
    return customer.id
```

Replace `_create_pending_attestation_fee` with attestation-only `_create_attestation` (drops the inline `Transaction` creation — the transaction now lives in `_fund_attestation`):

```python
async def _create_attestation(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    payload: AttestationRequestCreateRequest,
    amount: Decimal,
    initiator_is_owner: bool,
    status_value: str,
) -> UUID:
    """Persist the Attestation row (no transaction) and audit the request."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = Attestation(
            target_type=payload.target_type,
            target_id=payload.target_id,
            requestor_id=requestor_id,
            status=status_value,
            review_type=payload.review_type,
            brief=payload.brief.model_dump() if payload.brief is not None else None,
            requested_specializations=payload.requested_specializations,
            requested_jurisdictions=payload.requested_jurisdictions,
            fee_amount=amount,
            currency="USD",
        )
        db.add(attestation)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=requestor_id,
            action="attestation_requested",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "target_type": payload.target_type,
                "target_id": str(payload.target_id),
                "review_type": payload.review_type,
                "brief_provided": payload.brief is not None,
                "initiator_is_owner": initiator_is_owner,
            },
        )
        return attestation.id


async def _fund_attestation(
    db: AsyncSession,
    *,
    requestor: User,
    attestation_id: UUID,
    amount: Decimal,
    customer_id: str,
) -> AttestationFundingResponse:
    """Create the fee Transaction + Stripe PaymentIntent for a pending_fee request.

    Shared by owner-initiated request funding and operator post-consent funding.
    The caller (payer) receives the client_secret synchronously.
    """
    requestor_id = requestor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        user = await db.get(User, requestor_id, with_for_update=True)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        if user.stripe_customer_id is None:
            user.stripe_customer_id = customer_id
        transaction = Transaction(
            payer_id=requestor_id,
            payee_id=None,
            amount=amount,
            currency="USD",
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="attestation_fee",
            status="pending",
            provider="stripe",
            ref_id=attestation_id,
            ref_type="attestation",
        )
        db.add(transaction)
        await db.flush()
        transaction_id = transaction.id

    release_conditions = {
        "kind": "attestation",
        "attestation_id": str(attestation_id),
        "requestor_user_id": str(requestor_id),
    }
    try:
        payment_intent = await stripe.create_payment_intent(
            customer_id=customer_id,
            amount=amount,
            currency="USD",
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "escrow",
                "attestation_id": str(attestation_id),
                "release_conditions": json.dumps(release_conditions),
            },
            idempotency_key=f"attestation_fee:{transaction_id}",
        )
    except StripeProviderError as exc:
        await _mark_attestation_fee_provider_failed(
            db=db,
            requestor_id=requestor_id,
            transaction_id=transaction_id,
            attestation_id=attestation_id,
            reason="payment_intent_create_failed",
        )
        logger.bind(
            module="attestation",
            action="fund_attestation",
            user_id=requestor_id,
            transaction_id=transaction_id,
            attestation_id=attestation_id,
        ).error("stripe_payment_intent_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_attestation_fee_provider_ref(
        db=db,
        requestor_id=requestor_id,
        transaction_id=transaction_id,
        attestation_id=attestation_id,
        provider_ref=payment_intent.id,
    )
    logger.bind(
        module="attestation",
        action="fund_attestation",
        user_id=requestor_id,
        transaction_id=transaction_id,
        attestation_id=attestation_id,
    ).info("attestation_funded")
    return AttestationFundingResponse(
        id=attestation_id,
        transaction_id=transaction_id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )
```

Add a small framework-owner lookup helper (or reuse `_target_owner_id` from `matching_service` if exported; otherwise add locally):

```python
async def _target_framework_owner_id(db: AsyncSession, framework_id: UUID) -> UUID | None:
    """Return the contributor that owns a framework, or None if absent."""
    return await db.scalar(
        select(Framework.contributor_id).where(Framework.id == framework_id)
    )
```

Import `AttestationConsentPendingResponse` and `notify_consent_requested` access (`attestation_notifications` is already imported). Ensure `Framework` is imported (it is — used by `_validate_attestation_target`).

- [ ] **Step 5: Widen the endpoint response model**

In `router.py`, change the `POST /attestations` decorator + signature:

```python
@router.post(
    "/attestations",
    response_model=AttestationFundingResponse | AttestationConsentPendingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_attestation(
    payload: AttestationRequestCreateRequest,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationFundingResponse | AttestationConsentPendingResponse:
    """Create an Attestation request; fund now or await owner consent."""
    return await attestation_service.request_attestation(
        db=db, requestor=requestor, payload=payload
    )
```

Import `AttestationConsentPendingResponse` in `router.py`.

- [ ] **Step 6: Run the new test + the 2a regression suite**

Run: `cd backend && uv run pytest tests/integration/test_attestation_requests.py -v`
Expected: new test PASS; all existing owner-initiated tests still PASS (owner path unchanged — verify the owner-initiated request still returns `client_secret` + creates a transaction).

- [ ] **Step 7: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/service.py backend/app/modules/attestation/schemas.py backend/app/modules/attestation/router.py backend/app/modules/attestation/notifications.py backend/tests/integration/test_attestation_requests.py
git commit -m "feat(attestation): route operator-initiated requests through owner consent"
```

---

### Task 3: Owner consent endpoint (approve / decline)

**Files:**
- Modify: `backend/app/modules/attestation/service.py` (`decide_owner_consent`)
- Modify: `backend/app/modules/attestation/schemas.py` (`AttestationConsentRequest`)
- Modify: `backend/app/modules/attestation/router.py` (endpoint)
- Modify: `backend/app/modules/attestation/notifications.py` (approve/decline notices)
- Test: `backend/tests/integration/test_attestation_consent.py` (new)

**Interfaces:**
- Consumes: `Attestation`, `Framework`, `write_audit`, `CurrentUser`.
- Produces: `decide_owner_consent(db, owner, *, attestation_id, decision) -> Attestation`; `AttestationConsentRequest(decision: Literal["approve", "decline"])`; `notify_consent_approved`, `notify_consent_declined`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/integration/test_attestation_consent.py`:

```python
"""Owner-consent endpoint coverage for operator-initiated attestations (§2.5)."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.modules.attestation.models import Attestation

pytestmark = pytest.mark.asyncio


async def test_owner_approve_moves_to_pending_fee(
    client, owner_auth, pending_consent_attestation, db_session
):
    """The framework owner approving consent advances the request to pending_fee."""
    resp = await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/consent",
        headers=owner_auth,
        json={"decision": "approve"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_fee"


async def test_owner_decline_cancels(
    client, owner_auth, pending_consent_attestation
):
    """The framework owner declining consent cancels the request."""
    resp = await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/consent",
        headers=owner_auth,
        json={"decision": "decline"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_non_owner_consent_is_not_found(
    client, operator_auth, pending_consent_attestation
):
    """A non-owner (here, the operator requestor) gets 404 — no existence leak."""
    resp = await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/consent",
        headers=operator_auth,
        json={"decision": "approve"},
    )
    assert resp.status_code == 404


async def test_consent_wrong_status_conflicts(
    client, owner_auth, pending_consent_attestation, db_session
):
    """Consent on an attestation not in pending_owner_consent returns 409."""
    pending_consent_attestation.status = "matching"
    await db_session.commit()
    resp = await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/consent",
        headers=owner_auth,
        json={"decision": "approve"},
    )
    assert resp.status_code == 409
```

Add a `pending_consent_attestation` fixture (+ `owner_auth`) to `backend/tests/conftest.py` or the test module: a published framework with a known contributor (`owner_auth`), and an `Attestation(target_type="framework", target_id=framework.id, requestor_id=operator.id, status="pending_owner_consent", review_type="quality", brief={...}, fee_amount=Decimal("500.00"), currency="USD")` committed to the DB. Reuse existing framework/user factories.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestation_consent.py -v`
Expected: FAIL — endpoint 404 (route not defined).

- [ ] **Step 3: Add schema + notifications**

In `schemas.py`:

```python
class AttestationConsentRequest(BaseModel):
    """Framework-owner decision on an operator-initiated attestation request."""

    decision: Literal["approve", "decline"]
```

In `notifications.py`:

```python
def notify_consent_approved(attestation: Attestation) -> None:
    """Notify the requestor that the owner approved; funding may proceed."""
    _dispatch(
        attestation,
        recipient_id=attestation.requestor_id,
        notification_type="attestation_consent_approved",
        dedupe_suffix="consent-approved",
    )


def notify_consent_declined(attestation: Attestation) -> None:
    """Notify the requestor that the owner declined the attestation request."""
    _dispatch(
        attestation,
        recipient_id=attestation.requestor_id,
        notification_type="attestation_consent_declined",
        dedupe_suffix="consent-declined",
    )
```

- [ ] **Step 4: Implement the service**

In `service.py`:

```python
async def decide_owner_consent(
    db: AsyncSession,
    owner: User,
    *,
    attestation_id: UUID,
    decision: str,
) -> Attestation:
    """Approve or decline an operator-initiated attestation as the framework owner.

    Only the owner of the target framework may decide (any other caller gets 404,
    no existence leak). Approve advances to pending_fee for the operator to fund;
    decline cancels. Valid only while pending_owner_consent.

    Raises:
        HTTPException(404): Caller is not the target framework owner / not found.
        HTTPException(409): Attestation is not awaiting owner consent.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await db.get(Attestation, attestation_id, with_for_update=True)
        if attestation is None or attestation.target_type != "framework":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        owner_id = await db.scalar(
            select(Framework.contributor_id).where(
                Framework.id == attestation.target_id
            )
        )
        if owner_id != owner.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        if attestation.status != "pending_owner_consent":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation is not awaiting owner consent.",
            )
        if decision == "approve":
            attestation.status = "pending_fee"
            action = "attestation_consent_approved"
        else:
            attestation.status = "cancelled"
            attestation.closed_at = datetime.now(UTC)
            action = "attestation_consent_declined"
        await write_audit(
            db=db,
            actor_id=owner.id,
            action=action,
            target_type="attestation",
            target_id=attestation.id,
            metadata={"decision": decision},
        )
    await db.refresh(attestation)
    if decision == "approve":
        attestation_notifications.notify_consent_approved(attestation)
    else:
        attestation_notifications.notify_consent_declined(attestation)
    return attestation
```

(Confirm `datetime`, `UTC`, `select`, `Framework` are imported in `service.py`.)

- [ ] **Step 5: Add the endpoint**

In `router.py` (place after the `POST /attestations` endpoint):

```python
@router.post(
    "/attestations/{attestation_id}/consent",
    response_model=AttestationRequestResponse,
)
async def decide_owner_consent(
    attestation_id: UUID,
    payload: AttestationConsentRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Approve or decline an operator-initiated attestation as the framework owner."""
    attestation = await attestation_service.decide_owner_consent(
        db=db,
        owner=user,
        attestation_id=attestation_id,
        decision=payload.decision,
    )
    return AttestationRequestResponse.model_validate(attestation)
```

Import `AttestationConsentRequest`.

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_attestation_consent.py -v`
Expected: PASS (all four).

- [ ] **Step 7: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/service.py backend/app/modules/attestation/schemas.py backend/app/modules/attestation/router.py backend/app/modules/attestation/notifications.py backend/tests/integration/test_attestation_consent.py backend/tests/conftest.py
git commit -m "feat(attestation): add framework-owner consent endpoint"
```

---

### Task 4: Operator fund endpoint

**Files:**
- Modify: `backend/app/modules/attestation/service.py` (`fund_attestation`)
- Modify: `backend/app/modules/attestation/router.py` (endpoint)
- Test: `backend/tests/integration/test_attestation_consent.py`

**Interfaces:**
- Consumes: `_fund_attestation`, `_ensure_stripe_customer`, `Attestation`, `Transaction`.
- Produces: `fund_attestation(db, requestor, *, attestation_id) -> AttestationFundingResponse`; endpoint `POST /attestations/{id}/fund`.

- [ ] **Step 1: Write failing tests**

Add to `test_attestation_consent.py`:

```python
async def test_operator_funds_after_approval(
    client, operator_auth, owner_auth, pending_consent_attestation, stub_stripe
):
    """After owner approval, the operator funds and receives a client_secret."""
    await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/consent",
        headers=owner_auth,
        json={"decision": "approve"},
    )
    resp = await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/fund",
        headers=operator_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["client_secret"]


async def test_fund_rejects_when_not_pending_fee(
    client, operator_auth, pending_consent_attestation
):
    """Funding a request still awaiting consent (pending_owner_consent) is 409."""
    resp = await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/fund",
        headers=operator_auth,
    )
    assert resp.status_code == 409


async def test_fund_rejects_non_requestor(
    client, owner_auth, operator_auth, pending_consent_attestation
):
    """Only the operator requestor may fund (others get 404)."""
    await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/consent",
        headers=owner_auth,
        json={"decision": "approve"},
    )
    resp = await client.post(
        f"/v1/attestations/{pending_consent_attestation.id}/fund",
        headers=owner_auth,
    )
    assert resp.status_code == 404
```

(Reuse the existing Stripe stub fixture from the 2a request tests — same `stub_stripe` / monkeypatch that `test_attestation_requests.py` uses for `create_payment_intent`. Do not create a new stub.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestation_consent.py -k fund -v`
Expected: FAIL — `/fund` route undefined.

- [ ] **Step 3: Implement the service**

In `service.py`:

```python
async def fund_attestation(
    db: AsyncSession,
    requestor: User,
    *,
    attestation_id: UUID,
) -> AttestationFundingResponse:
    """Fund an owner-approved operator-initiated attestation as the requestor.

    Valid only when the caller is the requestor, the status is pending_fee, and no
    fee transaction exists yet (owner-initiated requests fund at creation and would
    already hold one).

    Raises:
        HTTPException(404): Caller is not the requestor / attestation not found.
        HTTPException(409): Not pending_fee, or already funded.
    """
    attestation = await db.get(Attestation, attestation_id)
    if attestation is None or attestation.requestor_id != requestor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if attestation.status != "pending_fee":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation is not awaiting payment.",
        )
    existing_txn = await db.scalar(
        select(Transaction.id).where(
            Transaction.ref_id == attestation_id,
            Transaction.ref_type == "attestation",
        )
    )
    if existing_txn is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation fee is already being processed.",
        )
    customer_id = await _ensure_stripe_customer(db, requestor)
    return await _fund_attestation(
        db=db,
        requestor=requestor,
        attestation_id=attestation_id,
        amount=attestation.fee_amount,
        customer_id=customer_id,
    )
```

- [ ] **Step 4: Add the endpoint**

In `router.py`:

```python
@router.post(
    "/attestations/{attestation_id}/fund",
    response_model=AttestationFundingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def fund_attestation(
    attestation_id: UUID,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationFundingResponse:
    """Fund an owner-approved operator-initiated attestation as the requestor."""
    return await attestation_service.fund_attestation(
        db=db, requestor=requestor, attestation_id=attestation_id
    )
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_attestation_consent.py -v`
Expected: PASS (all consent + fund tests).

- [ ] **Step 6: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/service.py backend/app/modules/attestation/router.py backend/tests/integration/test_attestation_consent.py
git commit -m "feat(attestation): add operator fund endpoint for approved requests"
```

---

### Task 5: Consent-timeout Beat task

**Files:**
- Modify: `backend/app/modules/attestation/matching_service.py` (`expire_owner_consent`)
- Modify: `backend/app/workers/tasks/attestation_beat.py` (wrapper)
- Modify: `backend/app/workers/beat_schedule.py` (schedule entry)
- Test: `backend/tests/unit/workers/test_attestation_beat.py` (or existing attestation-beat test module)

**Interfaces:**
- Consumes: `_platform_int_config`, `Attestation`, `write_audit`, `attestation_notifications.notify_consent_declined`.
- Produces: `expire_owner_consent(db) -> int`; Celery task `expire_owner_consent`; schedule key `expire-owner-consent-hourly`.

- [ ] **Step 1: Write failing test**

Add `backend/tests/unit/workers/test_attestation_consent_expiry.py`:

```python
"""Owner-consent timeout coverage (§2.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.attestation import matching_service
from app.modules.attestation.models import Attestation

pytestmark = pytest.mark.asyncio


async def test_stale_consent_is_cancelled(db_session, published_framework, operator):
    """A pending_owner_consent request older than the timeout is cancelled."""
    stale = Attestation(
        target_type="framework",
        target_id=published_framework.id,
        requestor_id=operator.id,
        status="pending_owner_consent",
        review_type="quality",
        fee_amount=Decimal("500.00"),
        currency="USD",
    )
    db_session.add(stale)
    await db_session.commit()
    # Force created_at into the past beyond the 72h window.
    stale.created_at = datetime.now(UTC) - timedelta(hours=73)
    await db_session.commit()

    count = await matching_service.expire_owner_consent(db_session)

    await db_session.refresh(stale)
    assert count == 1
    assert stale.status == "cancelled"


async def test_fresh_consent_untouched(db_session, published_framework, operator):
    """A recent pending_owner_consent request is left alone."""
    fresh = Attestation(
        target_type="framework",
        target_id=published_framework.id,
        requestor_id=operator.id,
        status="pending_owner_consent",
        review_type="quality",
        fee_amount=Decimal("500.00"),
        currency="USD",
    )
    db_session.add(fresh)
    await db_session.commit()

    count = await matching_service.expire_owner_consent(db_session)

    await db_session.refresh(fresh)
    assert count == 0
    assert fresh.status == "pending_owner_consent"
```

(Reuse existing `published_framework` / `operator` fixtures. `Attestation` has `created_at` from `UpdatedAtMixin`/`CreatedAtMixin`; confirm it carries `created_at` — it appears in `AttestationRequestResponse`, so it exists.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/workers/test_attestation_consent_expiry.py -v`
Expected: FAIL — `expire_owner_consent` undefined.

- [ ] **Step 3: Implement the service function**

In `matching_service.py` (mirror `expire_stale_offers` structure):

```python
async def expire_owner_consent(db: AsyncSession) -> int:
    """Cancel operator-initiated requests whose owner-consent window has elapsed.

    Reads attestation_owner_consent_hours (default 72) and cancels every
    pending_owner_consent attestation created before the cutoff. Idempotent.

    Returns:
        The number of attestations cancelled.
    """
    current_time = datetime.now(UTC)
    consent_hours = await _platform_int_config(
        db,
        key="attestation_owner_consent_hours",
        default=72,
        minimum=1,
    )
    cutoff = current_time - timedelta(hours=consent_hours)
    cancelled: list[Attestation] = []
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        rows = await db.execute(
            select(Attestation)
            .where(
                Attestation.status == "pending_owner_consent",
                Attestation.created_at <= cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        for attestation in rows.scalars().all():
            attestation.status = "cancelled"
            attestation.closed_at = current_time
            await write_audit(
                db=db,
                actor_id=None,
                action="attestation_consent_expired",
                target_type="attestation",
                target_id=attestation.id,
                metadata={"consent_hours": consent_hours},
            )
            cancelled.append(attestation)
    for attestation in cancelled:
        attestation_notifications.notify_consent_declined(attestation)
    return len(cancelled)
```

(Confirm `attestation_notifications` is imported in `matching_service.py` — it is, used by other functions.)

- [ ] **Step 4: Add the Beat wrapper + schedule**

In `attestation_beat.py` add the async helper + task (mirror `expire_attestation_offers`):

```python
async def _expire_owner_consent() -> int:
    """Cancel operator-initiated requests past their owner-consent window."""
    async with async_session_factory() as db:
        return await matching_service.expire_owner_consent(db)


@app.task(bind=True)  # type: ignore[untyped-decorator]
def expire_owner_consent(self: Any) -> dict[str, int]:
    """Celery wrapper for hourly owner-consent expiry."""
    log = logger.bind(
        module="attestation",
        action="expire_owner_consent",
        task_id=self.request.id,
    )
    log.info("task_started")
    cancelled_count = run_async(_expire_owner_consent())
    result = {"cancelled_count": cancelled_count}
    log.info("task_completed", result=result)
    return result
```

In `beat_schedule.py` add (next to the other attestation entries):

```python
    "expire-owner-consent-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_owner_consent",
        "schedule": 3600.0,
    },
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/workers/test_attestation_consent_expiry.py -v`
Expected: PASS.

- [ ] **Step 6: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/matching_service.py backend/app/workers/tasks/attestation_beat.py backend/app/workers/beat_schedule.py backend/tests/unit/workers/test_attestation_consent_expiry.py
git commit -m "feat(attestation): expire stale owner-consent requests on a schedule"
```

---

### Task 6: Per-accept content-use acknowledgment

**Files:**
- Modify: `backend/app/modules/attestation/schemas.py` (`AttestationAcceptRequest`)
- Modify: `backend/app/modules/attestation/matching_service.py` (`accept_attestation_offer`)
- Modify: `backend/app/modules/attestation/router.py` (accept endpoint body)
- Test: `backend/tests/integration/test_attestation_lifecycle.py` (or the existing accept-offer test module)

**Interfaces:**
- Consumes: existing `accept_attestation_offer` body.
- Produces: `AttestationAcceptRequest(content_ack: bool, ack_version: str)`; `accept_attestation_offer(..., content_ack: bool, ack_version: str)` sets `content_ack_at`/`content_ack_version`.

- [ ] **Step 1: Write failing tests**

Add to the existing accept-offer integration test module (find it via `grep -rl "/accept" backend/tests/integration`):

```python
async def test_accept_requires_content_ack(client, attestor_auth, offered_attestation):
    """Accepting without affirming the content-use acknowledgment returns 422."""
    resp = await client.post(
        f"/v1/attestations/{offered_attestation.id}/accept",
        headers=attestor_auth,
        json={"content_ack": False, "ack_version": "v1"},
    )
    assert resp.status_code == 422


async def test_accept_records_ack(
    client, attestor_auth, offered_attestation, db_session
):
    """Accepting with the acknowledgment records the version and timestamp."""
    resp = await client.post(
        f"/v1/attestations/{offered_attestation.id}/accept",
        headers=attestor_auth,
        json={"content_ack": True, "ack_version": "v1"},
    )
    assert resp.status_code == 200
    await db_session.refresh(offered_attestation)
    assert offered_attestation.content_ack_at is not None
    assert offered_attestation.content_ack_version == "v1"
```

(Reuse the existing `offered_attestation` / `attestor_auth` fixtures used by current accept tests. If accept tests currently send no body, the new required body will break them — update those existing accept calls to include `{"content_ack": True, "ack_version": "v1"}` as part of this task.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestation_lifecycle.py -k accept -v`
Expected: FAIL — endpoint takes no body / fields not recorded.

- [ ] **Step 3: Add the schema**

In `schemas.py`:

```python
class AttestationAcceptRequest(BaseModel):
    """Attestor acceptance with the binding content-use acknowledgment (§2.5)."""

    content_ack: bool
    ack_version: str = Field(min_length=1, max_length=50)
```

- [ ] **Step 4: Thread the ack through the service**

In `matching_service.py`, change `accept_attestation_offer` signature + body:

```python
async def accept_attestation_offer(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    attestor: User,
    content_ack: bool,
    ack_version: str,
) -> Attestation:
    """Accept a cohort offer and atomically assign the Attestation.

    Full framework-content access is gated on the content-use acknowledgment, so
    acceptance requires content_ack=True (§2.5).

    Raises:
        HTTPException(422): content_ack was not affirmed.
    """
    if not content_ack:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Content-use acknowledgment is required to accept.",
        )
    attestor_id = attestor.id
    ...
```

Inside the transaction, where `attestation.accepted_at = current_time` is set, also set:

```python
        attestation.content_ack_at = current_time
        attestation.content_ack_version = ack_version
```

- [ ] **Step 5: Update the endpoint**

In `router.py`, change the accept endpoint to take the body:

```python
@router.post(
    "/attestations/{attestation_id}/accept",
    response_model=AttestationRequestResponse,
)
async def accept_attestation_offer(
    attestation_id: UUID,
    payload: AttestationAcceptRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Accept an open Attestation cohort offer with the content-use acknowledgment."""
    attestation = await matching_service.accept_attestation_offer(
        db=db,
        attestation_id=attestation_id,
        attestor=attestor,
        content_ack=payload.content_ack,
        ack_version=payload.ack_version,
    )
    return AttestationRequestResponse.model_validate(attestation)
```

Import `AttestationAcceptRequest`.

- [ ] **Step 6: Run tests (including any other accept callers)**

Run: `cd backend && uv run pytest tests/integration -k accept -v`
Expected: PASS — new ack tests plus all updated existing accept tests.

- [ ] **Step 7: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/schemas.py backend/app/modules/attestation/matching_service.py backend/app/modules/attestation/router.py backend/tests/integration/
git commit -m "feat(attestation): require content-use acknowledgment to accept offers"
```

---

### Task 7: Entitlement computation (`access_service.py`)

**Files:**
- Create: `backend/app/modules/attestation/access_service.py`
- Test: `backend/tests/unit/modules/test_attestation_access_entitlement.py`

**Interfaces:**
- Consumes: `Attestation`, `AttestationOffer`, `User`.
- Produces: `attestation_access_scope(db, *, attestation, user) -> Literal["preview", "full", "none"]`; module constant `FULL_ACCESS_STATUSES = frozenset({"accepted", "report_submitted", "disputed"})`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/modules/test_attestation_access_entitlement.py`:

```python
"""Entitlement matrix for the Attestation access package (§2.5)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.attestation import access_service
from app.modules.attestation.models import Attestation, AttestationOffer

pytestmark = pytest.mark.asyncio


async def _make_attestation(db, *, requestor, attestor_id, status, ack=True):
    att = Attestation(
        target_type="framework",
        target_id=requestor.id,  # placeholder target; not dereferenced here
        requestor_id=requestor.id,
        attestor_id=attestor_id,
        status=status,
        review_type="quality",
        fee_amount=Decimal("500.00"),
        currency="USD",
        content_ack_at=__import__("datetime").datetime.now(__import__("datetime").UTC)
        if ack
        else None,
        content_ack_version="v1" if ack else None,
    )
    db.add(att)
    await db.commit()
    return att


async def test_assigned_accepted_with_ack_is_full(db_session, operator, attestor):
    """The assigned attestor with an acknowledgment and accepted status gets full."""
    att = await _make_attestation(
        db_session, requestor=operator, attestor_id=attestor.id, status="accepted"
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "full"


@pytest.mark.parametrize("status", ["report_submitted", "disputed"])
async def test_review_states_are_full(db_session, operator, attestor, status):
    """Report-submitted and disputed keep full access for the assigned attestor."""
    att = await _make_attestation(
        db_session, requestor=operator, attestor_id=attestor.id, status=status
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "full"


async def test_accepted_without_ack_is_none(db_session, operator, attestor):
    """Accepted but missing the acknowledgment yields no access."""
    att = await _make_attestation(
        db_session, requestor=operator, attestor_id=attestor.id,
        status="accepted", ack=False,
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "none"


@pytest.mark.parametrize("status", ["released", "resolved", "refunded", "closed", "cancelled"])
async def test_terminal_states_revoke_full(db_session, operator, attestor, status):
    """Terminal statuses (including resolved) drop the assigned attestor to none."""
    att = await _make_attestation(
        db_session, requestor=operator, attestor_id=attestor.id, status=status
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "none"


async def test_cohort_offer_is_preview(db_session, operator, attestor):
    """A cohort member with a live offer gets preview, not full."""
    att = await _make_attestation(
        db_session, requestor=operator, attestor_id=None, status="offered"
    )
    db_session.add(
        AttestationOffer(
            attestation_id=att.id,
            attestor_id=attestor.id,
            cohort_index=0,
            status="offered",
        )
    )
    await db_session.commit()
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "preview"


async def test_outsider_is_none(db_session, operator, attestor):
    """A user with neither assignment nor a live offer gets none."""
    att = await _make_attestation(
        db_session, requestor=operator, attestor_id=None, status="offered"
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "none"
```

(Reuse `operator` / `attestor` user fixtures. The `AttestationOffer` constructor fields must match the model — confirm `offered_at` is nullable or has a server default; if required, add `offered_at=datetime.now(UTC)`.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestation_access_entitlement.py -v`
Expected: FAIL — `access_service` module does not exist.

- [ ] **Step 3: Implement**

Create `backend/app/modules/attestation/access_service.py`:

```python
"""Attestation access-package entitlement, presigned access, and audit (§2.5).

Entitlement is derived from live Attestation/Offer status — never stored — so
revocation is automatic. Full content access additionally requires the per-accept
content-use acknowledgment recorded on the attestation row.

Maps to: FR §2.5 (Framework Access Package).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import Attestation, AttestationOffer
from app.modules.auth.models import User

AccessScope = Literal["preview", "full", "none"]

FULL_ACCESS_STATUSES = frozenset({"accepted", "report_submitted", "disputed"})


async def attestation_access_scope(
    db: AsyncSession,
    *,
    attestation: Attestation,
    user: User,
) -> AccessScope:
    """Compute a user's access scope for an attestation's framework content.

    Args:
        db: Async session.
        attestation: The attestation whose content is being accessed.
        user: The requesting user.

    Returns:
        "full" for the assigned attestor in a review state with an acknowledgment,
        "preview" for a cohort member holding a live offer, otherwise "none".
    """
    if (
        attestation.attestor_id == user.id
        and attestation.status in FULL_ACCESS_STATUSES
        and attestation.content_ack_at is not None
    ):
        return "full"
    offer_status = await db.scalar(
        select(AttestationOffer.status).where(
            AttestationOffer.attestation_id == attestation.id,
            AttestationOffer.attestor_id == user.id,
        )
    )
    if offer_status == "offered":
        return "preview"
    return "none"
```

(Confirm the import path for `User` matches the codebase — other attestation services import `from app.modules.auth.models import User`. Match whatever they use.)

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestation_access_entitlement.py -v`
Expected: PASS (all parametrizations).

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/access_service.py backend/tests/unit/modules/test_attestation_access_entitlement.py
git commit -m "feat(attestation): compute access-package entitlement from status"
```

---

### Task 8: Artifact-access presign endpoint + access log

**Files:**
- Modify: `backend/app/modules/attestation/access_service.py` (`request_artifact_access`)
- Modify: `backend/app/modules/attestation/schemas.py` (`AttestationArtifactAccessResponse`)
- Modify: `backend/app/modules/attestation/router.py` (endpoint)
- Test: `backend/tests/integration/test_attestation_access.py` (new)

**Interfaces:**
- Consumes: `attestation_access_scope`, `matching_service.get_attestation_for_user`, `Artifact`, `Framework`, `FrameworkVersionArtifact`, `AttestationArtifactAccess`, `s3.storage.presigned_get`, `write_audit`.
- Produces: `request_artifact_access(db, user, *, attestation_id, artifact_id, ip) -> AttestationArtifactAccessResponse`; `AttestationArtifactAccessResponse(artifact_id, attestation_id, scope, download_url, expires_in)`; endpoint `POST /attestations/{id}/artifacts/{artifact_id}/access`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/integration/test_attestation_access.py`:

```python
"""Attestation artifact-access presign + audit coverage (§2.5)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.modules.attestation.models import AttestationArtifactAccess

pytestmark = pytest.mark.asyncio


async def test_assigned_attestor_full_access_logs(
    client, attestor_auth, accepted_attestation, framework_artifact, db_session, stub_s3
):
    """The assigned attestor gets a presigned URL and the access is logged."""
    resp = await client.post(
        f"/v1/attestations/{accepted_attestation.id}"
        f"/artifacts/{framework_artifact.id}/access",
        headers=attestor_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["download_url"]
    count = await db_session.scalar(
        select(func.count())
        .select_from(AttestationArtifactAccess)
        .where(AttestationArtifactAccess.attestation_id == accepted_attestation.id)
    )
    assert count == 1


async def test_preview_scope_rejects_non_preview_artifact(
    client, attestor_auth, offered_attestation, framework_artifact, stub_s3
):
    """A cohort member (preview scope) cannot presign a non-preview artifact."""
    resp = await client.post(
        f"/v1/attestations/{offered_attestation.id}"
        f"/artifacts/{framework_artifact.id}/access",
        headers=attestor_auth,
    )
    assert resp.status_code == 403


async def test_outsider_gets_forbidden(
    client, other_attestor_auth, accepted_attestation, framework_artifact
):
    """A user with no entitlement is forbidden."""
    resp = await client.post(
        f"/v1/attestations/{accepted_attestation.id}"
        f"/artifacts/{framework_artifact.id}/access",
        headers=other_attestor_auth,
    )
    assert resp.status_code in (403, 404)
```

(Fixtures: `accepted_attestation` = an attestation assigned to the `attestor`, status `accepted`, `content_ack_at` set, target a published framework with `framework_artifact`. `offered_attestation` = same framework, status `offered`, an `AttestationOffer(status="offered")` for the attestor. `stub_s3` = the existing presign stub used by library download tests; reuse it. `framework_artifact` belongs to the framework and is NOT the preview artifact.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestation_access.py -v`
Expected: FAIL — route undefined.

- [ ] **Step 3: Add the response schema**

In `schemas.py`:

```python
class AttestationArtifactAccessResponse(BaseModel):
    """Presigned access grant for an Attestation framework artifact."""

    artifact_id: UUID
    attestation_id: UUID
    scope: str
    download_url: str
    expires_in: int
```

- [ ] **Step 4: Implement the service**

Append to `access_service.py`:

```python
ARTIFACT_ACCESS_URL_TTL_SECONDS = 900


async def _artifact_is_preview_eligible(
    db: AsyncSession, *, framework_id: UUID, artifact_id: UUID
) -> bool:
    """Return True when the artifact is the framework preview or a preview version artifact."""
    preview_artifact_id = await db.scalar(
        select(Framework.preview_artifact_id).where(Framework.id == framework_id)
    )
    if preview_artifact_id == artifact_id:
        return True
    flagged = await db.scalar(
        select(FrameworkVersionArtifact.artifact_id)
        .where(
            FrameworkVersionArtifact.artifact_id == artifact_id,
            FrameworkVersionArtifact.is_preview.is_(True),
        )
        .limit(1)
    )
    return flagged is not None


async def request_artifact_access(
    db: AsyncSession,
    user: User,
    *,
    attestation_id: UUID,
    artifact_id: UUID,
    ip_address: str | None,
) -> AttestationArtifactAccessResponse:
    """Issue an entitlement-checked presigned URL for an Attestation artifact.

    Raises:
        HTTPException(403): Insufficient entitlement, or preview scope on a
            non-preview artifact.
        HTTPException(404): Attestation not visible, or artifact not part of the
            target framework.
    """
    settings = get_settings()
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await matching_service.get_attestation_for_user(
            db, attestation_id=attestation_id, user=user
        )
        scope = await attestation_access_scope(db, attestation=attestation, user=user)
        if scope == "none":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No access to this Attestation's content.",
            )
        artifact = await db.scalar(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.framework_id == attestation.target_id,
            )
        )
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact not found.",
            )
        if scope == "preview" and not await _artifact_is_preview_eligible(
            db, framework_id=attestation.target_id, artifact_id=artifact_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Preview access does not cover this Artifact.",
            )
        download_url = s3.storage.presigned_get(
            settings.s3_artifacts_bucket,
            artifact.file_key,
            ARTIFACT_ACCESS_URL_TTL_SECONDS,
        )
        db.add(
            AttestationArtifactAccess(
                attestation_id=attestation.id,
                attestor_id=user.id,
                artifact_id=artifact.id,
                scope=scope,
                ip_address=ip_address,
            )
        )
        await write_audit(
            db=db,
            actor_id=user.id,
            action="attestation_artifact_accessed",
            target_type="artifact",
            target_id=artifact.id,
            metadata={"attestation_id": str(attestation.id), "scope": scope},
        )
    logger.bind(
        module="attestation",
        action="request_artifact_access",
        user_id=user.id,
        attestation_id=attestation_id,
        artifact_id=artifact_id,
    ).info("attestation_artifact_accessed")
    return AttestationArtifactAccessResponse(
        artifact_id=artifact_id,
        attestation_id=attestation_id,
        scope=scope,
        download_url=download_url,
        expires_in=ARTIFACT_ACCESS_URL_TTL_SECONDS,
    )
```

Add the imports at the top of `access_service.py`:

```python
from fastapi import HTTPException, status
from loguru import logger

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation import matching_service
from app.modules.attestation.models import AttestationArtifactAccess
from app.modules.attestation.schemas import AttestationArtifactAccessResponse
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact, FrameworkVersionArtifact
```

(Confirm `FrameworkVersionArtifact` is the class name in `models_artifact.py` — the table is `framework_version_artifacts`; match the actual class name. Confirm `s3.storage.presigned_get` and `settings.s3_artifacts_bucket` match the library service usage exactly.)

- [ ] **Step 5: Add the endpoint**

In `router.py` (use `Request` for the client IP, as `library/router.py` does):

```python
@router.post(
    "/attestations/{attestation_id}/artifacts/{artifact_id}/access",
    response_model=AttestationArtifactAccessResponse,
)
async def request_attestation_artifact_access(
    attestation_id: UUID,
    artifact_id: UUID,
    request: Request,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestationArtifactAccessResponse:
    """Issue an entitlement-checked presigned URL for an Attestation artifact."""
    return await access_service.request_artifact_access(
        db=db,
        user=user,
        attestation_id=attestation_id,
        artifact_id=artifact_id,
        ip_address=request.client.host if request.client else None,
    )
```

Add `Request` to the `fastapi` import, import `access_service` and `AttestationArtifactAccessResponse`.

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_attestation_access.py -v`
Expected: PASS.

- [ ] **Step 7: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/access_service.py backend/app/modules/attestation/schemas.py backend/app/modules/attestation/router.py backend/tests/integration/test_attestation_access.py
git commit -m "feat(attestation): presign attestor artifact access with audit logging"
```

---

### Task 9: Access-package endpoint

**Files:**
- Modify: `backend/app/modules/attestation/access_service.py` (`get_attestation_package`)
- Modify: `backend/app/modules/attestation/schemas.py` (`AttestationPackageResponse`, `AttestationPackageArtifact`)
- Modify: `backend/app/modules/attestation/router.py` (endpoint)
- Test: `backend/tests/integration/test_attestation_access.py`

**Interfaces:**
- Consumes: `attestation_access_scope`, `matching_service.get_attestation_for_user`, `Framework`, `Artifact`, `FrameworkVersionArtifact`.
- Produces: `get_attestation_package(db, user, *, attestation_id) -> AttestationPackageResponse`; endpoint `GET /attestations/{id}/package`.

- [x] **Step 1: Write failing tests**

Add to `test_attestation_access.py`:

```python
async def test_package_full_lists_all_artifacts(
    client, attestor_auth, accepted_attestation, framework_artifact
):
    """The assigned attestor's package reports full scope and lists all artifacts."""
    resp = await client.get(
        f"/v1/attestations/{accepted_attestation.id}/package",
        headers=attestor_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entitlement"] == "full"
    assert any(a["id"] == str(framework_artifact.id) for a in body["artifacts"])


async def test_package_preview_lists_only_preview(
    client, attestor_auth, offered_attestation, framework_artifact, preview_artifact
):
    """A cohort member's package reports preview scope and only preview artifacts."""
    resp = await client.get(
        f"/v1/attestations/{offered_attestation.id}/package",
        headers=attestor_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entitlement"] == "preview"
    ids = {a["id"] for a in body["artifacts"]}
    assert str(preview_artifact.id) in ids
    assert str(framework_artifact.id) not in ids


async def test_package_outsider_not_found(
    client, other_attestor_auth, accepted_attestation
):
    """A non-participant cannot see the package."""
    resp = await client.get(
        f"/v1/attestations/{accepted_attestation.id}/package",
        headers=other_attestor_auth,
    )
    assert resp.status_code == 404
```

(Add a `preview_artifact` fixture: an artifact set as the framework's `preview_artifact_id` or flagged `is_preview` on its version-artifact row.)

- [x] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestation_access.py -k package -v`
Expected: FAIL — route undefined.

- [x] **Step 3: Add schemas**

In `schemas.py`:

```python
class AttestationPackageArtifact(BaseModel):
    """One artifact entry in an Attestation access package."""

    id: UUID
    filename: str | None = None


class AttestationPackageResponse(BaseModel):
    """The read-only Attestation access package scoped to the caller's entitlement."""

    attestation_id: UUID
    framework_title: str
    framework_category: str
    framework_industry: str | None
    brief: dict[str, Any] | None
    entitlement: str
    artifacts: list[AttestationPackageArtifact]
```

(Confirm `Any` is imported in `schemas.py` — it is, used by `AttestationRequestResponse`. Use the artifact's real display field for `filename`; check `Artifact` for a `filename`/`original_filename` column and map it, else drop the field.)

- [x] **Step 4: Implement the service**

Append to `access_service.py`:

```python
async def get_attestation_package(
    db: AsyncSession,
    user: User,
    *,
    attestation_id: UUID,
) -> AttestationPackageResponse:
    """Assemble the access package scoped to the caller's entitlement.

    Returns framework metadata, the brief, the computed entitlement, and an artifact
    list — the preview subset for preview scope, all artifacts for full, empty for none.
    """
    attestation = await matching_service.get_attestation_for_user(
        db, attestation_id=attestation_id, user=user
    )
    scope = await attestation_access_scope(db, attestation=attestation, user=user)
    framework = await db.get(Framework, attestation.target_id)
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    artifacts: list[AttestationPackageArtifact] = []
    if scope == "full":
        rows = await db.execute(
            select(Artifact).where(Artifact.framework_id == framework.id)
        )
        artifacts = [
            AttestationPackageArtifact(id=a.id) for a in rows.scalars().all()
        ]
    elif scope == "preview":
        preview_ids: set[UUID] = set()
        if framework.preview_artifact_id is not None:
            preview_ids.add(framework.preview_artifact_id)
        flagged = await db.execute(
            select(FrameworkVersionArtifact.artifact_id).where(
                FrameworkVersionArtifact.is_preview.is_(True),
            )
        )
        for (artifact_id,) in flagged.all():
            preview_ids.add(artifact_id)
        if preview_ids:
            rows = await db.execute(
                select(Artifact).where(
                    Artifact.framework_id == framework.id,
                    Artifact.id.in_(preview_ids),
                )
            )
            artifacts = [
                AttestationPackageArtifact(id=a.id) for a in rows.scalars().all()
            ]
    return AttestationPackageResponse(
        attestation_id=attestation.id,
        framework_title=framework.title,
        framework_category=framework.category,
        framework_industry=framework.industry,
        brief=attestation.brief,
        entitlement=scope,
        artifacts=artifacts,
    )
```

Import `AttestationPackageResponse`, `AttestationPackageArtifact` in `access_service.py`.

- [x] **Step 5: Add the endpoint**

In `router.py`:

```python
@router.get(
    "/attestations/{attestation_id}/package",
    response_model=AttestationPackageResponse,
)
async def get_attestation_package(
    attestation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestationPackageResponse:
    """Return the read-only Attestation access package for a participant."""
    return await access_service.get_attestation_package(
        db=db, user=user, attestation_id=attestation_id
    )
```

Import `AttestationPackageResponse`.

- [x] **Step 6: Run tests + full attestation suite**

Run: `cd backend && uv run pytest tests/integration/test_attestation_access.py tests/unit/modules/test_attestation_access_entitlement.py -v`
Then: `cd backend && uv run pytest tests/integration/test_attestation_requests.py tests/integration/test_attestation_consent.py -v`
Expected: all PASS.

- [x] **Step 7: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/access_service.py backend/app/modules/attestation/schemas.py backend/app/modules/attestation/router.py backend/tests/integration/test_attestation_access.py
git commit -m "feat(attestation): serve the scoped framework access package"
```

---

## Final verification (after all tasks)

- [x] Full attestation test suite green: `cd backend && uv run pytest tests/unit/modules/test_attestation_access_entitlement.py tests/unit/test_attestation_access_package_migration.py tests/unit/workers/test_attestation_consent_expiry.py tests/integration/test_attestation_requests.py tests/integration/test_attestation_consent.py tests/integration/test_attestation_access.py -v`
- [x] Whole-repo gates: `cd backend && uv run ruff check . && uv run mypy app`
- [x] Migration round-trip: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- [x] Spec coverage: §2.5 deltas 1–4 all implemented (consent gate T2–T5; preview T7/T9; full unlock + ack T6–T9; access log T8). DRM, watermarking, blanket onboarding NDA explicitly out of scope.
- [x] OpenAPI: regenerate `contracts/openapi.yaml` from the new endpoints (consent, fund, artifact access, package) per workflow rule 7, then regenerate the frontend client. (Backend-only plan; frontend UI is a later slice.)

## Module 1 follow-up (flagged, not in this plan)

Add a one-time attestor confidentiality / non-use agreement (`confidentiality_signed_at`) to `AttestorApplication` and gate offer-acceptance on it. 2b's per-accept acknowledgment stands alone until then.
