# Attestation Module 2a — Request Submission Reshape Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the existing escrow-funded Attestation request flow in line with workflow-doc §2.1–2.4 — add a review-type dimension, a structured brief, review-tier framework fees, operator-initiated requests on published frameworks, and a 10-day SLA — without disturbing the working escrow integration or the downstream lifecycle.

**Architecture:** Additive reshape of the interim flow. `Attestation.target_type` (framework/contributor/operator/credential) stays as the lifecycle spine; a new orthogonal `review_type` (quality/compliance/expert/provenance) and a `brief` JSONB column are added. Fee resolution becomes a function of `(target_type, review_type)`: framework targets are priced by review tier, all other targets keep their existing flat fees. Owner notification on operator-initiated requests fires from the existing webhook funding-completion path.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, PostgreSQL 16, pytest + httpx AsyncClient, Stripe (escrow), Celery notifications, loguru.

## Global Constraints

- Source of truth: `docs/Auracles Attestation — Product Development Workflow.md` §2.1–2.4. Spec: `docs/superpowers/specs/2026-06-30-attestation-module-2a-request-submission-design.md`.
- Review-type enum values exactly: `quality`, `compliance`, `expert`, `provenance`.
- Framework fees exactly: Quality `500.00`, Compliance `1200.00`, Expert `2500.00`, Provenance `500.00` (Provenance = Quality tier per spec open-decision default).
- SLA config exactly `10` (calendar days, interim parity) for all four target types; was `7`.
- Non-framework target fees unchanged: framework-as-target `250.00` is **not** used once review-tier applies; contributor `300.00`, operator `300.00`, credential `100.00` stay.
- Migration head to extend: `2026_06_29_0043`. New revision id: `2026_06_30_0044`. Both `alembic upgrade head` and `alembic downgrade -1` must succeed.
- All changes additive + backward-compatible. `review_type`/`brief` are nullable at the DB layer; "required for framework" is enforced in the service (HTTP 422), never as a DB NOT NULL.
- Pydantic on every input; `brief` is a typed nested model, never a raw dict. No raw-dict access.
- Brief contents are never logged and never returned in list endpoints to non-participants (it may carry sensitive business detail). Audit logs record presence/flags only.
- Money path untouched: PaymentIntent → `escrow_service.hold` is not modified. All multi-row writes stay inside the existing owner-transaction (`async with db.begin()`).
- Deny by default: a non-owned, non-published framework target returns 404 (no existence leak).
- Endpoint is `POST /v1/attestations` (router has no internal prefix; mounted at `/v1` in `app/main.py`).
- Out of scope: §2.5 Framework Access Package (→ Module 2b), dispute-window value change (→ Module 5), AMM consumption of `review_type` (→ Module 3), business-day SLA arithmetic.

---

## File Structure

- `backend/app/modules/attestation/models.py` — add `ATTESTATION_REVIEW_TYPE_ENUM`; add `review_type` + `brief` columns to `Attestation`.
- `backend/migrations/versions/2026_06_30_0044_attestation_review_type_and_fees.py` (new) — enum, columns, config seeds, SLA bump.
- `backend/app/modules/attestation/schemas.py` — `AttestationBrief` model; extend `AttestationRequestCreateRequest` + `AttestationRequestResponse`.
- `backend/app/modules/attestation/service.py` — fee resolution, conditional-required enforcement, persistence, target validation, dup-guard.
- `backend/app/modules/attestation/notifications.py` — `notify_request_received_for_owner`.
- `backend/app/modules/webhooks/service.py` — owner notification on funding completion.
- `backend/tests/unit/test_attestation_review_type_migration.py` (new) — migration coverage.
- `backend/tests/integration/test_attestation_requests.py` — extend with review-type, brief, fee, operator-initiated, dup-guard, owner-notify cases (+ fixture seed updates).

---

### Task 1: Migration + model — review_type enum, brief column, fees, SLA

**Files:**
- Modify: `backend/app/modules/attestation/models.py` (enum block after line 119; `Attestation` columns after line 458)
- Create: `backend/migrations/versions/2026_06_30_0044_attestation_review_type_and_fees.py`
- Modify: `backend/tests/integration/test_attestation_requests.py:108-118` (fixture seeds)
- Test: `backend/tests/unit/test_attestation_review_type_migration.py` (new)

**Interfaces:**
- Produces: `ATTESTATION_REVIEW_TYPE_ENUM` (name `attestation_review_type_enum`); `Attestation.review_type: Mapped[str | None]`; `Attestation.brief: Mapped[dict[str, Any] | None]`; config keys `attestation_fee_review_{quality,compliance,expert,provenance}`; SLA keys set to `10`.

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/unit/test_attestation_review_type_migration.py`:

```python
"""Migration coverage for Module 2a review-type, brief, fees, and SLA."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PRIOR_HEAD = "2026_06_29_0043"


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Upgrade to head and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_review_type_columns_enum_and_config(migrated_engine: Engine) -> None:
    """Upgrade adds review_type/brief, the enum, review fees, and SLA = 10."""
    inspector = inspect(migrated_engine)
    columns = {col["name"] for col in inspector.get_columns("attestations")}
    with migrated_engine.connect() as connection:
        enums = {
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typname = 'attestation_review_type_enum'")
            )
        }
        config = {
            row.key: row.value
            for row in connection.execute(text("SELECT key, value FROM platform_config"))
        }

    assert {"review_type", "brief"}.issubset(columns)
    assert "attestation_review_type_enum" in enums
    assert config["attestation_fee_review_quality"] == "500.00"
    assert config["attestation_fee_review_compliance"] == "1200.00"
    assert config["attestation_fee_review_expert"] == "2500.00"
    assert config["attestation_fee_review_provenance"] == "500.00"
    assert config["attestation_completion_sla_days_framework"] == "10"
    assert config["attestation_completion_sla_days_credential"] == "10"


def test_downgrade_reverts_review_type_changes() -> None:
    """Downgrade drops the columns/enum, removes review fees, restores SLA = 7."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PRIOR_HEAD)
    try:
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("attestations")}
        with engine.connect() as connection:
            enums = {
                row[0]
                for row in connection.execute(
                    text("SELECT typname FROM pg_type WHERE typname = 'attestation_review_type_enum'")
                )
            }
            config_keys = {
                row[0]
                for row in connection.execute(text("SELECT key FROM platform_config"))
            }
        assert "review_type" not in columns
        assert "brief" not in columns
        assert "attestation_review_type_enum" not in enums
        assert "attestation_fee_review_quality" not in config_keys
        assert config := next(
            (
                row[0]
                for row in engine.connect().execute(
                    text(
                        "SELECT value FROM platform_config "
                        "WHERE key = 'attestation_completion_sla_days_framework'"
                    )
                )
            ),
            None,
        )
        assert config == "7"
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_attestation_review_type_migration.py -v`
Expected: FAIL — `attestation_review_type_enum` missing / columns absent / config keys absent (migration not written yet).

- [ ] **Step 3: Add the enum + columns to the model**

In `backend/app/modules/attestation/models.py`, after the `ATTESTATION_UPLOAD_SCAN_STATUS_ENUM` block (ends line 127), add:

```python
ATTESTATION_REVIEW_TYPE_ENUM = ENUM(
    "quality",
    "compliance",
    "expert",
    "provenance",
    name="attestation_review_type_enum",
    create_type=False,
)
```

In the `Attestation` class, immediately after the `outcome` column (line 442), add:

```python
    review_type: Mapped[str | None] = mapped_column(
        ATTESTATION_REVIEW_TYPE_ENUM, nullable=True
    )
    brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

(`Any` and `JSONB` are already imported in this file.)

- [ ] **Step 4: Write the migration**

Create `backend/migrations/versions/2026_06_30_0044_attestation_review_type_and_fees.py`:

```python
"""Add attestation review_type + brief, review-tier fees, and 10-day SLA.

Implements Module 2a (workflow-doc §2.1–2.4): an orthogonal review-type
dimension and structured brief on attestation requests, review-tier framework
fees, and the 10-business-day SLA value. Additive and backward-compatible;
review_type/brief are nullable so interim rows survive.

Revision ID: 2026_06_30_0044
Revises: 2026_06_29_0043
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "2026_06_30_0044"
down_revision = "2026_06_29_0043"
branch_labels = None
depends_on = None

REVIEW_TYPE_ENUM = postgresql.ENUM(
    "quality",
    "compliance",
    "expert",
    "provenance",
    name="attestation_review_type_enum",
)

REVIEW_FEE_SEEDS = {
    "attestation_fee_review_quality": "500.00",
    "attestation_fee_review_compliance": "1200.00",
    "attestation_fee_review_expert": "2500.00",
    "attestation_fee_review_provenance": "500.00",
}

SLA_KEYS = (
    "attestation_completion_sla_days_framework",
    "attestation_completion_sla_days_contributor",
    "attestation_completion_sla_days_operator",
    "attestation_completion_sla_days_credential",
)


def upgrade() -> None:
    """Create the review-type enum, columns, fees, and 10-day SLA."""
    bind = op.get_bind()
    REVIEW_TYPE_ENUM.create(bind, checkfirst=True)
    op.add_column(
        "attestations",
        sa.Column(
            "review_type",
            postgresql.ENUM(name="attestation_review_type_enum", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "attestations",
        sa.Column("brief", postgresql.JSONB(), nullable=True),
    )

    for key, value in REVIEW_FEE_SEEDS.items():
        op.execute(
            sa.text(
                """
                INSERT INTO platform_config (key, value)
                VALUES (:key, :value)
                ON CONFLICT (key) DO NOTHING
                """
            ).bindparams(key=key, value=value)
        )
    for key in SLA_KEYS:
        op.execute(
            sa.text(
                "UPDATE platform_config SET value = '10' WHERE key = :key"
            ).bindparams(key=key)
        )


def downgrade() -> None:
    """Drop the review-type columns/enum, remove fees, restore 7-day SLA."""
    bind = op.get_bind()
    for key in SLA_KEYS:
        op.execute(
            sa.text(
                "UPDATE platform_config SET value = '7' WHERE key = :key"
            ).bindparams(key=key)
        )
    for key in REVIEW_FEE_SEEDS:
        op.execute(
            sa.text("DELETE FROM platform_config WHERE key = :key").bindparams(key=key)
        )
    op.drop_column("attestations", "brief")
    op.drop_column("attestations", "review_type")
    REVIEW_TYPE_ENUM.drop(bind, checkfirst=True)
```

- [ ] **Step 5: Update the integration-test fixture seeds**

In `backend/tests/integration/test_attestation_requests.py`, in `reset_attestation_state` (the dict at lines 108-113), replace the seed dict so review fees + SLA = 10 are deterministic across resets:

```python
            for key, value in {
                "attestation_fee_framework": "250.00",
                "attestation_fee_contributor": "300.00",
                "attestation_fee_operator": "300.00",
                "attestation_fee_credential": "100.00",
                "attestation_fee_review_quality": "500.00",
                "attestation_fee_review_compliance": "1200.00",
                "attestation_fee_review_expert": "2500.00",
                "attestation_fee_review_provenance": "500.00",
                "attestation_completion_sla_days_framework": "10",
                "attestation_completion_sla_days_contributor": "10",
                "attestation_completion_sla_days_operator": "10",
                "attestation_completion_sla_days_credential": "10",
            }.items():
```

- [ ] **Step 6: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_attestation_review_type_migration.py tests/unit/test_attestation_schema_foundation.py -v`
Expected: PASS (new migration test green; schema-foundation test still green).

- [ ] **Step 7: Commit**

```bash
git add app/modules/attestation/models.py migrations/versions/2026_06_30_0044_attestation_review_type_and_fees.py tests/unit/test_attestation_review_type_migration.py tests/integration/test_attestation_requests.py
git commit -m "feat(attestation): add review_type + brief columns, review-tier fees, 10-day SLA"
```

---

### Task 2: Request + response schemas (review_type, brief)

**Files:**
- Modify: `backend/app/modules/attestation/schemas.py:463-499`
- Test: `backend/tests/integration/test_attestation_requests.py`

**Interfaces:**
- Consumes: nothing from prior tasks (pure schema).
- Produces: `AttestationBrief`; `AttestationRequestCreateRequest.review_type: str | None`, `.brief: AttestationBrief | None`; `AttestationRequestResponse.review_type: str | None`, `.brief: dict | None`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_attestation_requests.py`:

```python
def test_attestation_brief_rejects_blank_fields() -> None:
    """A brief with an empty required field fails Pydantic validation."""
    from pydantic import ValidationError

    from app.modules.attestation.schemas import AttestationBrief

    with pytest.raises(ValidationError):
        AttestationBrief(
            what_it_does="",
            use_case="growth team",
            jurisdiction="US",
            focus_areas="AML coverage",
            desired_outcome="compliance sign-off",
        )


def test_attestation_request_accepts_review_type_and_brief() -> None:
    """The create schema accepts a review_type and a structured brief."""
    from app.modules.attestation.schemas import AttestationRequestCreateRequest

    payload = AttestationRequestCreateRequest(
        target_type="framework",
        target_id="11111111-1111-1111-1111-111111111111",
        review_type="compliance",
        brief={
            "what_it_does": "Standardises KYC onboarding",
            "use_case": "Compliance team at a mid-size fund",
            "jurisdiction": "US",
            "focus_areas": "AML completeness",
            "desired_outcome": "Compliance sign-off badge",
        },
        requested_specializations=["compliance"],
        requested_jurisdictions=["US"],
    )
    assert payload.review_type == "compliance"
    assert payload.brief is not None
    assert payload.brief.jurisdiction == "US"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_attestation_request_accepts_review_type_and_brief" "tests/integration/test_attestation_requests.py::test_attestation_brief_rejects_blank_fields" -v`
Expected: FAIL — `AttestationBrief` does not exist / `review_type` not a field.

- [ ] **Step 3: Add the schemas**

In `backend/app/modules/attestation/schemas.py`, immediately before `class AttestationRequestCreateRequest` (line 463), add:

```python
class AttestationBrief(BaseModel):
    """Structured review brief shown to the cohort during the offer phase."""

    what_it_does: str = Field(min_length=1, max_length=2000)
    use_case: str = Field(min_length=1, max_length=2000)
    jurisdiction: str = Field(min_length=1, max_length=200)
    focus_areas: str = Field(min_length=1, max_length=2000)
    desired_outcome: str = Field(min_length=1, max_length=2000)
```

Then extend `AttestationRequestCreateRequest` (currently lines 463-469) to:

```python
class AttestationRequestCreateRequest(BaseModel):
    """Request body for creating an escrow-funded Attestation request."""

    target_type: Literal["framework", "contributor", "operator", "credential"]
    target_id: UUID
    review_type: Literal["quality", "compliance", "expert", "provenance"] | None = None
    brief: AttestationBrief | None = None
    requested_specializations: list[str] = Field(min_length=1, max_length=25)
    requested_jurisdictions: list[str] = Field(min_length=1, max_length=25)
```

Then in `AttestationRequestResponse` (line 472), add these two fields after `outcome: str | None` (line 481):

```python
    review_type: str | None = None
    brief: dict[str, Any] | None = None
```

(`Literal`, `Field`, `Any` are already imported in this file.)

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_attestation_request_accepts_review_type_and_brief" "tests/integration/test_attestation_requests.py::test_attestation_brief_rejects_blank_fields" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/schemas.py tests/integration/test_attestation_requests.py
git commit -m "feat(attestation): add review_type + structured brief to request schemas"
```

---

### Task 3: Fee resolution by review type

**Files:**
- Modify: `backend/app/modules/attestation/service.py:40-45` (defaults), `:261-275` (`_attestation_fee`)
- Test: `backend/tests/integration/test_attestation_requests.py`

**Interfaces:**
- Consumes: config keys from Task 1.
- Produces: `_attestation_fee(db, target_type, review_type) -> Decimal`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_attestation_requests.py`:

```python
async def test_attestation_fee_resolves_by_review_type(
    migrated_database: None,
    attestation_context: FakeRedis,
) -> None:
    """Framework fees follow the review tier; other targets keep flat fees."""
    del migrated_database, attestation_context
    from app.core.database import async_session_factory
    from app.modules.attestation.service import _attestation_fee

    async with async_session_factory() as session:
        assert await _attestation_fee(session, "framework", "quality") == Decimal("500.00")
        assert await _attestation_fee(session, "framework", "compliance") == Decimal("1200.00")
        assert await _attestation_fee(session, "framework", "expert") == Decimal("2500.00")
        assert await _attestation_fee(session, "framework", "provenance") == Decimal("500.00")
        assert await _attestation_fee(session, "credential", None) == Decimal("100.00")
        assert await _attestation_fee(session, "contributor", None) == Decimal("300.00")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_attestation_fee_resolves_by_review_type" -v`
Expected: FAIL — `_attestation_fee()` takes 2 positional args, got 3.

- [ ] **Step 3: Update defaults + fee resolution**

In `backend/app/modules/attestation/service.py`, extend `ATTESTATION_FEE_DEFAULTS` (lines 40-45) to:

```python
ATTESTATION_FEE_DEFAULTS = {
    "framework": Decimal("250.00"),
    "contributor": Decimal("300.00"),
    "operator": Decimal("300.00"),
    "credential": Decimal("100.00"),
}
ATTESTATION_REVIEW_FEE_DEFAULTS = {
    "quality": Decimal("500.00"),
    "compliance": Decimal("1200.00"),
    "expert": Decimal("2500.00"),
    "provenance": Decimal("500.00"),
}
```

Replace `_attestation_fee` (lines 261-275) with:

```python
async def _attestation_fee(
    db: AsyncSession,
    target_type: str,
    review_type: str | None,
) -> Decimal:
    """Return the configured fee for a target, priced by review tier for frameworks.

    Framework attestations are priced by their review type (Quality/Compliance/
    Expert/Provenance). All other targets keep their flat per-target fee.

    Args:
        db: Async session for the platform_config lookup.
        target_type: The attestation target kind.
        review_type: The review lens; required when target_type is "framework".

    Returns:
        The two-decimal fee amount.

    Raises:
        HTTPException(422): Framework target without a review_type.
        HTTPException(500): Configured fee value is not a valid decimal.
    """
    if target_type == "framework":
        if review_type is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Framework attestation requires a review type.",
            )
        key = f"attestation_fee_review_{review_type}"
        default = ATTESTATION_REVIEW_FEE_DEFAULTS[review_type]
    else:
        key = f"attestation_fee_{target_type}"
        default = ATTESTATION_FEE_DEFAULTS[target_type]

    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == key)
    )
    if configured is None:
        return default
    try:
        return _normalise_money(Decimal(configured))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{key} configuration is invalid.",
        ) from exc
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_attestation_fee_resolves_by_review_type" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/service.py tests/integration/test_attestation_requests.py
git commit -m "feat(attestation): price framework attestations by review tier"
```

---

### Task 4: Require + persist review_type/brief in request flow

**Files:**
- Modify: `backend/app/modules/attestation/service.py:78-101` (`request_attestation` head), `:278-340` (`_create_pending_attestation_fee`)
- Test: `backend/tests/integration/test_attestation_requests.py`

**Interfaces:**
- Consumes: `_attestation_fee(db, target_type, review_type)` (Task 3); `_validate_attestation_target` returning `bool` (defined here, finalized in Task 5).
- Produces: persisted `Attestation.review_type`/`.brief`; audit metadata with `review_type` + `initiator_is_owner`.

> Note: this task introduces `initiator_is_owner` as the return value of `_validate_attestation_target`. In Task 5 that function's body is fully rewritten; here it is changed to return `True` on every existing accepted path (owner/self), preserving current behaviour. Task 5 then relaxes the framework branch to return `False` for the published non-owner case.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_attestation_requests.py`:

```python
async def _stub_stripe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch Stripe customer + PaymentIntent creation with fakes."""
    async def fake_create_customer(*, email, name=None, idempotency_key=None):
        return FakeStripeCustomer("cus_fw_1")

    async def fake_create_payment_intent(
        *, customer_id, amount, currency, metadata, idempotency_key=None
    ):
        return FakeStripePaymentIntent("pi_fw_1", "pi_fw_secret")

    monkeypatch.setattr(stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(stripe, "create_payment_intent", fake_create_payment_intent)


async def _create_framework(owner_id: UUID, status_value: str = "published") -> UUID:
    """Create one Framework owned by owner_id in the given status."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=owner_id,
                title="KYC Onboarding Framework",
                slug=f"kyc-{owner_id}",
                summary="Standardises onboarding",
                status=status_value,
            )
            session.add(framework)
            await session.flush()
            return framework.id


_BRIEF = {
    "what_it_does": "Standardises KYC onboarding",
    "use_case": "Compliance team at a mid-size fund",
    "jurisdiction": "US",
    "focus_areas": "AML completeness",
    "desired_outcome": "Compliance sign-off badge",
}


async def test_framework_request_persists_review_type_and_brief(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A framework attestation stores its review type, brief, and tier fee."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-owner@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "compliance",
            "brief": _BRIEF,
            "requested_specializations": ["compliance"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert response.status_code == 201
    attestation_id = UUID(response.json()["id"])
    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
    assert attestation.review_type == "compliance"
    assert attestation.brief == _BRIEF
    assert attestation.fee_amount == Decimal("1200.00")


async def test_framework_request_requires_review_type_and_brief(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A framework request missing review_type or brief is rejected with 422."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-owner-2@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "requested_specializations": ["compliance"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert response.status_code == 422
```

(If `Framework` requires fields beyond those shown, adjust `_create_framework` to satisfy them — inspect `app/modules/frameworks/models.py` for non-null columns without defaults before running.)

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_framework_request_persists_review_type_and_brief" "tests/integration/test_attestation_requests.py::test_framework_request_requires_review_type_and_brief" -v`
Expected: FAIL — review_type/brief not persisted (and/or framework target rejected by current owner-only validation; Task 5 finalizes that, but the contributor here IS the owner so it should pass validation once persistence is wired).

- [ ] **Step 3: Wire requirement check, fee call, and persistence**

In `backend/app/modules/attestation/service.py`, replace the head of `request_attestation` (lines 89-101) with:

```python
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
```

Then change the `_create_pending_attestation_fee` call (lines 122-128) to pass `initiator_is_owner`:

```python
    attestation_id, transaction_id = await _create_pending_attestation_fee(
        db=db,
        requestor_id=requestor_id,
        customer_id=customer_id,
        payload=payload,
        amount=amount,
        initiator_is_owner=initiator_is_owner,
    )
```

In `_create_pending_attestation_fee` (line 278), add the parameter and persist the new fields. Change the signature line and the `Attestation(...)` construction + audit metadata:

```python
async def _create_pending_attestation_fee(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    customer_id: str,
    payload: AttestationRequestCreateRequest,
    amount: Decimal,
    initiator_is_owner: bool,
) -> tuple[UUID, UUID]:
```

```python
        attestation = Attestation(
            target_type=payload.target_type,
            target_id=payload.target_id,
            requestor_id=requestor_id,
            status="pending_fee",
            review_type=payload.review_type,
            brief=payload.brief.model_dump() if payload.brief is not None else None,
            requested_specializations=payload.requested_specializations,
            requested_jurisdictions=payload.requested_jurisdictions,
            fee_amount=amount,
            currency="USD",
        )
```

```python
            metadata={
                "target_type": payload.target_type,
                "target_id": str(payload.target_id),
                "transaction_id": str(transaction.id),
                "review_type": payload.review_type,
                "brief_provided": payload.brief is not None,
                "initiator_is_owner": initiator_is_owner,
            },
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_framework_request_persists_review_type_and_brief" "tests/integration/test_attestation_requests.py::test_framework_request_requires_review_type_and_brief" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/service.py tests/integration/test_attestation_requests.py
git commit -m "feat(attestation): require and persist review_type + brief for framework requests"
```

---

### Task 5: Operator-initiated validation + review-type-aware dup guard

**Files:**
- Modify: `backend/app/modules/attestation/service.py:190-258` (`_validate_attestation_target`, `_reject_duplicate_in_flight_request`)
- Test: `backend/tests/integration/test_attestation_requests.py`

**Interfaces:**
- Consumes: `Framework` (already imported in `service.py`).
- Produces: `_validate_attestation_target(...) -> bool` (True = requestor owns/self target; False = published non-owner framework); `_reject_duplicate_in_flight_request(..., review_type)`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_attestation_requests.py`:

```python
async def test_operator_can_request_on_published_framework_they_dont_own(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator may request attestation on a published framework they don't own."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    owner_id = await create_user("fw-author@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "published")

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _BRIEF,
            "requested_specializations": ["operations"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert response.status_code == 201


async def test_operator_cannot_request_on_unpublished_framework(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-owner requesting on an unpublished framework gets 404 (no leak)."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    owner_id = await create_user("fw-author-2@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer-2@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "draft")

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _BRIEF,
            "requested_specializations": ["operations"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert response.status_code == 404


async def test_same_target_different_review_type_allowed(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quality and Compliance on the same framework are independent requests."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-multi@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    base = {
        "target_type": "framework",
        "target_id": str(framework_id),
        "brief": _BRIEF,
        "requested_specializations": ["compliance"],
        "requested_jurisdictions": ["US"],
    }

    first = await client.post("/v1/attestations", headers=headers, json={**base, "review_type": "quality"})
    assert first.status_code == 201
    second = await client.post("/v1/attestations", headers=headers, json={**base, "review_type": "compliance"})
    assert second.status_code == 201
    duplicate = await client.post("/v1/attestations", headers=headers, json={**base, "review_type": "quality"})
    assert duplicate.status_code == 409
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_operator_can_request_on_published_framework_they_dont_own" "tests/integration/test_attestation_requests.py::test_operator_cannot_request_on_unpublished_framework" "tests/integration/test_attestation_requests.py::test_same_target_different_review_type_allowed" -v`
Expected: FAIL — current validation rejects non-owner framework (404 even when published) and dup guard ignores review_type.

- [ ] **Step 3: Rewrite validation + dup guard**

In `backend/app/modules/attestation/service.py`, replace `_validate_attestation_target` (lines 190-233) with:

```python
async def _validate_attestation_target(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    target_type: str,
    target_id: UUID,
) -> bool:
    """Ensure the requestor may request attestation on the target.

    Owners may request on their own credential/profile; the framework owner may
    request on their own framework in any status. A non-owner may request on a
    framework only when it is published (workflow-doc §2.1) — an unpublished or
    non-existent framework yields 404 with no existence leak.

    Returns:
        True when the requestor owns or is the target (credential/contributor/
        operator, or owned framework); False when it is a published framework the
        requestor does not own.

    Raises:
        HTTPException(404): Target not found, or unpublished framework not owned.
    """
    if target_type == "credential":
        credential = await db.scalar(
            select(Credential.id).where(
                Credential.id == target_id,
                Credential.user_id == requestor_id,
            )
        )
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found.",
            )
        return True

    if target_type == "framework":
        framework = await db.scalar(
            select(Framework.contributor_id, Framework.status).where(
                Framework.id == target_id,
                Framework.deleted_at.is_(None),
            )
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        contributor_id, framework_status = framework
        if contributor_id == requestor_id:
            return True
        if framework_status == "published":
            return False
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )

    if target_type in {"contributor", "operator"} and target_id == requestor_id:
        return True

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Attestation target not found.",
    )
```

Replace `_reject_duplicate_in_flight_request` (lines 236-258) with:

```python
async def _reject_duplicate_in_flight_request(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    target_type: str,
    target_id: UUID,
    review_type: str | None,
) -> None:
    """Reject a duplicate in-flight request for the same target and review type.

    A requestor may run different review types (e.g. Quality and Compliance) on
    the same target concurrently — only an identical (target, review_type) pair
    already in flight is blocked.
    """
    existing_id = await db.scalar(
        select(Attestation.id)
        .where(
            Attestation.requestor_id == requestor_id,
            Attestation.target_type == target_type,
            Attestation.target_id == target_id,
            Attestation.review_type.is_(review_type)
            if review_type is None
            else Attestation.review_type == review_type,
            Attestation.status.in_(IN_FLIGHT_ATTESTATION_STATUSES),
        )
        .limit(1)
    )
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An Attestation request for this target is already in flight.",
        )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_operator_can_request_on_published_framework_they_dont_own" "tests/integration/test_attestation_requests.py::test_operator_cannot_request_on_unpublished_framework" "tests/integration/test_attestation_requests.py::test_same_target_different_review_type_allowed" "tests/integration/test_attestation_requests.py::test_operator_requests_credential_attestation_with_stripe_escrow" -v`
Expected: PASS (including the pre-existing credential test — its dup-check now passes `review_type=None`).

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/service.py tests/integration/test_attestation_requests.py
git commit -m "feat(attestation): allow operator-initiated requests on published frameworks"
```

---

### Task 6: Notify framework owner on operator-initiated funding

**Files:**
- Modify: `backend/app/modules/attestation/notifications.py` (new helper after line 80)
- Modify: `backend/app/modules/webhooks/service.py:523-557`
- Test: `backend/tests/integration/test_attestation_requests.py`

**Interfaces:**
- Consumes: `Attestation.target_type`, `.requestor_id`; `Framework.contributor_id`.
- Produces: `notify_request_received_for_owner(attestation, *, owner_id)`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_attestation_requests.py`:

```python
async def test_owner_notified_on_operator_initiated_funding(
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Funding an operator-initiated framework request notifies the owner."""
    del migrated_database, attestation_context
    from app.modules.attestation import notifications as attn
    from app.modules.webhooks import service as webhook_service
    from app.modules.financials.models import Escrow, Transaction

    captured: list[UUID] = []

    def fake_owner_notify(attestation, *, owner_id):
        captured.append(owner_id)

    monkeypatch.setattr(attn, "notify_request_received_for_owner", fake_owner_notify)
    monkeypatch.setattr(
        webhook_service.attestation_notifications,
        "notify_request_received_for_owner",
        fake_owner_notify,
    )

    owner_id = await create_user("fw-owner-notify@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer-notify@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "published")

    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=framework_id,
                requestor_id=operator_id,
                status="pending_fee",
                review_type="quality",
                brief=_BRIEF,
                requested_specializations=["operations"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("500.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=None,
                amount=Decimal("500.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("500.00"),
                transaction_type="attestation_fee",
                status="completed",
                provider="stripe",
                provider_ref="pi_owner_notify",
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            escrow = Escrow(
                ref_id=attestation.id,
                ref_type="attestation",
                amount=Decimal("500.00"),
                currency="USD",
                status="held",
                release_conditions={},
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            transaction_id, escrow_id = transaction.id, escrow.id

    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.get(Transaction, transaction_id)
            escrow = await session.get(Escrow, escrow_id)
            callbacks = await webhook_service._apply_attestation_fee_funded(
                session, transaction=transaction, escrow=escrow
            )
    for callback in callbacks:
        callback()

    assert captured == [owner_id]
```

(Confirm the funding-apply function's exact name by reading `webhooks/service.py` around line 514 before writing the test; the block lives in the function whose body is shown at lines 515-557. Use that name in the test call.)

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_owner_notified_on_operator_initiated_funding" -v`
Expected: FAIL — `notify_request_received_for_owner` does not exist.

- [ ] **Step 3: Add the notification helper**

In `backend/app/modules/attestation/notifications.py`, after `notify_fee_funded` (ends line 80), add:

```python
def notify_request_received_for_owner(
    attestation: Attestation,
    *,
    owner_id: UUID,
) -> None:
    """Notify a framework owner that someone requested attestation on it.

    Fires only for operator-initiated requests (requestor is not the owner).
    """
    _dispatch(
        user_id=owner_id,
        notification_type="attestation_requested_on_your_framework",
        title="Attestation requested on your framework",
        body="Someone requested an independent attestation on your published framework.",
        attestation=attestation,
        dedupe_suffix="owner",
    )
```

- [ ] **Step 4: Wire it into the funding-completion path**

In `backend/app/modules/webhooks/service.py`, inside the attestation-fee-funded apply function, after `offers = await matching_service.offer_next_cohort(...)` (line 548) and before the `return [...]`, add an owner lookup, then append the owner callback to the returned list. Replace lines 548-557 with:

```python
    offers = await matching_service.offer_next_cohort(db, attestation_id=attestation.id)

    owner_id: UUID | None = None
    if attestation.target_type == "framework":
        owner_id = await db.scalar(
            select(Framework.contributor_id).where(Framework.id == attestation.target_id)
        )
    callbacks: list[Callable[[], None]] = [
        lambda: attestation_notifications.notify_fee_funded(attestation),
        lambda: attestation_notifications.notify_offers(attestation, offers),
        lambda: (
            attestation_notifications.notify_needs_admin(attestation)
            if attestation.status == "needs_admin"
            else None
        ),
    ]
    if owner_id is not None and owner_id != attestation.requestor_id:
        resolved_owner_id = owner_id
        callbacks.append(
            lambda: attestation_notifications.notify_request_received_for_owner(
                attestation, owner_id=resolved_owner_id
            )
        )
    return callbacks
```

Ensure `Framework` and `UUID` are imported in `webhooks/service.py` (add `from app.modules.frameworks.models import Framework` and `from uuid import UUID` if absent; check the import block first). `select` and `Callable` are already used in this file.

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest "tests/integration/test_attestation_requests.py::test_owner_notified_on_operator_initiated_funding" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/attestation/notifications.py app/modules/webhooks/service.py tests/integration/test_attestation_requests.py
git commit -m "feat(attestation): notify framework owner on operator-initiated request funding"
```

---

### Task 7: Full-suite + lint/type gate

**Files:** none (verification only).

- [ ] **Step 1: Run the attestation + webhook suites**

Run: `uv run pytest tests/integration/test_attestation_requests.py tests/integration/test_attestation_matching.py tests/unit/test_attestation_review_type_migration.py tests/unit/test_attestation_schema_foundation.py tests/integration/test_webhooks.py -v`
Expected: all PASS. (Matching + webhook suites confirm the fee-signature and funding-path changes didn't regress downstream.)

- [ ] **Step 2: Whole-repo lint + type**

Run: `uv run ruff check . && uv run mypy app`
Expected: `All checks passed!` and `Success: no issues found`.

- [ ] **Step 3: Migration round-trip**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed.

- [ ] **Step 4: Commit (only if any fixups were needed)**

```bash
git add -A
git commit -m "test(attestation): module 2a full-suite + lint/type green"
```

---

## Self-Review

**Spec coverage:**
- §2.1 review-type selection → Tasks 1, 2, 4. ✅
- §2.1 operator-initiated → Task 5. ✅
- §2.2 structured brief → Tasks 2, 4. ✅
- §2.3 fee tiers → Tasks 1, 3. ✅
- §2.4 SLA 10 → Task 1. ✅
- Owner notification → Task 6. ✅
- Dup-guard review-type refinement → Task 5. ✅
- Audit `review_type` + `initiator_is_owner` → Task 4. ✅
- Out-of-scope (access package, dispute window, AMM scoring) → not built. ✅

**Type consistency:** `_attestation_fee(db, target_type, review_type)` signature defined in Task 3, consumed in Task 4. `_validate_attestation_target(...) -> bool` defined in Task 4's note, finalized in Task 5, consumed in Task 4's call site. `_reject_duplicate_in_flight_request(..., review_type)` signature added in Task 5, called with `review_type=` in Task 4. **Ordering note:** Task 4 calls `_validate_attestation_target` expecting a `bool` return and `_reject_duplicate_in_flight_request` with a `review_type` kwarg, but those functions are only rewritten in Task 5. Implement Task 4 and Task 5 in sequence and run Task 5's suite (which re-runs the credential happy path) before considering either complete; alternatively fold Tasks 4+5 into one commit if the reviewer prefers. The bodies are split only because each carries a distinct, independently reviewable behavior.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Two explicit "inspect before running" notes (Framework non-null columns in Task 4; funding-apply function name + imports in Task 6) are verification instructions, not placeholders — the surrounding code is complete.
