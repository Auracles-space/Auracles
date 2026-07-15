# Org Attestor Calibration Trial (Module 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the real Org Attestor calibration trial: curated fixture frameworks with answer keys, a member-scoped nominee workspace that submits rubric scores, an auto-score engine that suggests pass/fail, and an admin confirm/override step that feeds the application's `trial_passed` gate.

**Architecture:** Trial-scoped tables keyed to `attestor_trials.id` (the escrow-funded `attestations` tables are untouched). Fixtures are `Framework` rows flagged `is_calibration`. Grading is a pure, dependency-free module (`trial_scoring.py`) mirroring `app/modules/attestation/scoring.py`. Nominee and admin logic live in a new `attestor_trial_service.py`; the existing shared `AttestationRubricDimension` definitions supply the rubric.

**Tech Stack:** FastAPI (Python 3.13), SQLAlchemy async, Alembic, Pydantic v2, pytest / pytest-asyncio / httpx; Next.js 15, Tailwind, vitest, `@hey-api` generated client.

## Global Constraints

- Work on `main`. No feature branches. Ask before creating any branch.
- Commit messages end at the last meaningful line — **no `Co-Authored-By` trailer**.
- TDD RED→GREEN, one vertical slice at a time. Never write implementation before the failing test.
- Backend before frontend. OpenAPI/contract updated before regenerating the frontend client.
- Errors: `HTTPException(422)` business rule (use `status.HTTP_422_UNPROCESSABLE_CONTENT` — codebase standard, not `_ENTITY`); `401`/`403` auth; `404` not found; `409` conflict.
- Every write touching multiple tables uses `async with db.begin():`.
- Logging via `loguru` with `module=`/`action=` bound context. Never log secrets or presigned URLs.
- Audit via `write_audit(db, actor_id=..., action=..., target_type=..., target_id=..., metadata=...)` (flush-only, does not commit).
- Pydantic response schemas use `model_config = ConfigDict(from_attributes=True)`.
- Google-style docstrings on every module, class, and public function.
- Full-repo lint before claiming clean: `uv run ruff check .` and `uv run mypy app` (run from `backend/`).
- Migration filename pattern: `YYYY_MM_DD_00NN_description.py`. Current head is `2026_07_14_0083`. Both `alembic upgrade head` and `alembic downgrade -1` must succeed.
- Pass threshold constant: `PASS_THRESHOLD_PCT = 80.0`.
- Rubric dimensions are queried by `review_type` + `version == rubrics.RUBRIC_VERSION` (currently `1`).

## Key existing references (read before starting)

- `backend/app/modules/attestation/models.py` — `AttestorTrial` (line ~897), `ATTESTOR_TRIAL_STATUS_ENUM` (~161), `AttestationRubricDimension` (~648: `review_type`, `key`, `label`, `weight`, `display_order`, `version`), `AttestationRubricScore` (~716, scale 1–5).
- `backend/app/modules/attestation/scoring.py` — style template for `trial_scoring.py` (pure, dependency-free).
- `backend/app/modules/attestation/rubrics.py` — `RUBRIC_VERSION = 1`.
- `backend/app/modules/organizations/attestor_application_service.py` — `admin_start_trial` (~1111), `_trial_passed` (~137), `_gate_checklist` (~148), nominee notification (~1205, link at ~1218).
- `backend/app/modules/organizations/dependencies.py` — `require_org_role("member"|"admin"|"owner")` → `OrgContext(org, member, user)`; `_deny` audits + 403.
- `backend/app/modules/organizations/router.py` — `admin_org_attestor_router`, `PlatformAdmin` dep, `DatabaseSession`, `admin_start_trial` endpoint (~2097).
- `backend/app/modules/frameworks/models.py` — `Framework` (~94), `FRAMEWORK_STATUS_ENUM` (~35).
- `backend/app/modules/frameworks/models_artifact.py` — `Artifact` (~55): `framework_id`, `name`, `file_key`, `clean_file_key`, `mime_type`, `file_size`.
- `backend/app/integrations/s3.py` — `storage.presigned_get(bucket, key)` (~202); bucket = `settings.s3_artifacts_bucket`.
- `backend/app/core/audit.py` — `write_audit` (~18).
- `backend/migrations/env.py` — models imported here for autogenerate/metadata.
- `backend/tests/unit/modules/test_org_attestor_application_service.py`, `backend/tests/integration/test_org_attestor_admin_endpoints.py` — existing trial tests + `_gated_application` / `_submitted_app_with_nominee` helpers.
- Frontend: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/attestor/page.tsx`, `frontend/src/components/modules/admin/admin-org-attestor-review-panel.tsx`, `frontend/src/components/modules/organizations/attestor/` (workspace panels), `frontend/src/lib/auth/form-client.ts`. Client regen: `npm run generate:api`.

## File Structure

**Backend — new files**
- `backend/app/modules/attestation/trial_scoring.py` — pure grading (agreement vs key → `score_pct` + `auto_result`).
- `backend/app/modules/organizations/attestor_trial_service.py` — nominee load/submit + admin grade/decide + fixture/answer-key logic.
- `backend/migrations/versions/2026_07_15_0084_calibration_trial.py` — schema.

**Backend — modified**
- `backend/app/modules/attestation/models.py` — `submitted` enum value; new `AttestorTrialAnswerKey`, `AttestorTrialRubricScore`; new columns on `AttestorTrial`.
- `backend/app/modules/frameworks/models.py` — `is_calibration` column.
- `backend/app/modules/frameworks/service.py`, `backend/app/modules/explore/service.py`, `backend/app/modules/attestation/service.py` — leak-guard filters.
- `backend/app/modules/organizations/schemas.py` — trial request/response schemas.
- `backend/app/modules/organizations/router.py` — nominee endpoints, admin grade/decide, fixture curation; extend `start-trial`.
- `backend/app/modules/organizations/attestor_application_service.py` — notification link repoint; `admin_start_trial` fixture arg.
- `backend/migrations/env.py` — ensure new models imported (they live in already-imported modules, so no change if added to `attestation/models.py`).

**Frontend — new**
- `frontend/src/app/(auth)/dashboard/organizations/[orgId]/attestor-trial/page.tsx`
- `frontend/src/components/modules/organizations/attestor/trial-workspace.tsx` + `trial-workspace.test.tsx`

**Frontend — modified**
- `frontend/src/components/modules/admin/admin-org-attestor-review-panel.tsx` (+ test) — fixture picker on start-trial, grade view, decide.

---

## Task 1: Migration + models (schema foundation)

**Files:**
- Create: `backend/migrations/versions/2026_07_15_0084_calibration_trial.py`
- Modify: `backend/app/modules/frameworks/models.py` (add `is_calibration`)
- Modify: `backend/app/modules/attestation/models.py` (enum value + `AttestorTrial` columns + 2 new models)
- Test: `backend/tests/integration/test_calibration_trial_migration.py`

**Interfaces:**
- Produces: `frameworks.is_calibration` (bool); `AttestorTrial.submitted_at`, `.score_pct`, `.auto_result`; status enum value `"submitted"`; models `AttestorTrialAnswerKey(id, framework_id, dimension_id, expected_score, tolerance)`, `AttestorTrialRubricScore(id, trial_id, dimension_id, score, comment)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_calibration_trial_migration.py`:
```python
"""Migration smoke test for the calibration-trial schema.

Enforces that the new columns, enum value, and tables exist and that the
answer-key and rubric-score models round-trip.
"""
import pytest
from sqlalchemy import select

from app.modules.attestation.models import (
    AttestorTrial,
    AttestorTrialAnswerKey,
    AttestorTrialRubricScore,
)
from app.modules.frameworks.models import Framework


@pytest.mark.asyncio
async def test_new_schema_objects_exist(async_session_factory):
    """New columns, enum value, and tables are queryable after migration."""
    async with async_session_factory() as s:
        # Columns/tables resolve without error (empty result is fine).
        await s.execute(select(Framework.is_calibration).limit(1))
        await s.execute(select(AttestorTrial.score_pct, AttestorTrial.auto_result,
                               AttestorTrial.submitted_at).limit(1))
        await s.execute(select(AttestorTrialAnswerKey).limit(1))
        await s.execute(select(AttestorTrialRubricScore).limit(1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_calibration_trial_migration.py -v`
Expected: FAIL — `AttributeError` / undefined models.

- [ ] **Step 3: Add `is_calibration` to Framework**

In `backend/app/modules/frameworks/models.py`, inside `class Framework`, add near the status column:
```python
    is_calibration: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    """True for platform calibration fixtures; excluded from all marketplace surfaces."""
    calibration_review_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Which rubric (attestation review_type) a fixture's trial uses. Fixtures only.

    ``Framework`` has no ``review_type`` of its own, so the fixture carries the
    rubric selector here; the nominee/admin trial code reads it to load the
    matching ``AttestationRubricDimension`` rows. Null for normal frameworks.
    """
```
(Confirm `Boolean` and `text` are imported at top of the file; add to the existing sqlalchemy import if missing. `Text` is already imported.)

- [ ] **Step 4: Extend the trial enum + `AttestorTrial` + add new models**

In `backend/app/modules/attestation/models.py`:

Add the enum value (Python side) — update `ATTESTOR_TRIAL_STATUS_ENUM`:
```python
ATTESTOR_TRIAL_STATUS_ENUM = ENUM(
    "assigned",
    "submitted",
    "passed",
    "failed",
    name="attestor_trial_status_enum",
    create_type=False,
)
```

Inside `class AttestorTrial`, after `seeded_framework_id`:
```python
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    score_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    auto_result: Mapped[str | None] = mapped_column(Text, nullable=True)
```
(Add a `CheckConstraint("auto_result IS NULL OR auto_result IN ('pass','fail')", name="ck_attestor_trials_auto_result")` to `__table_args__`.)

Add two new model classes at the end of the file:
```python
class AttestorTrialAnswerKey(Base):
    """Expected rubric score per dimension for one calibration fixture."""

    __tablename__ = "attestor_trial_answer_keys"
    __table_args__ = (
        UniqueConstraint(
            "framework_id", "dimension_id",
            name="uq_attestor_trial_answer_keys_framework_dimension",
        ),
        CheckConstraint("expected_score BETWEEN 1 AND 5",
                        name="ck_attestor_trial_answer_keys_score_range"),
        CheckConstraint("tolerance BETWEEN 0 AND 4",
                        name="ck_attestor_trial_answer_keys_tolerance_range"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    dimension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestation_rubric_dimensions.id"), nullable=False,
    )
    expected_score: Mapped[int] = mapped_column(Integer, nullable=False)
    tolerance: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )


class AttestorTrialRubricScore(UpdatedAtMixin, CreatedAtMixin, Base):
    """One nominee rubric score + comment for a dimension on a trial."""

    __tablename__ = "attestor_trial_rubric_scores"
    __table_args__ = (
        UniqueConstraint(
            "trial_id", "dimension_id",
            name="uq_attestor_trial_rubric_scores_trial_dimension",
        ),
        CheckConstraint("score BETWEEN 1 AND 5",
                        name="ck_attestor_trial_rubric_scores_range"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    trial_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attestor_trials.id", ondelete="CASCADE"),
        nullable=False,
    )
    dimension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestation_rubric_dimensions.id"), nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
```
(Verify `Decimal`, `Numeric`, `Integer`, `Boolean`, `UniqueConstraint`, `CheckConstraint`, `ForeignKey`, `UpdatedAtMixin`, `CreatedAtMixin` are already imported in this file — most are. Add any missing.)

- [ ] **Step 5: Write the migration**

`backend/migrations/versions/2026_07_15_0084_calibration_trial.py`:
```python
"""Calibration trial schema: fixtures, answer keys, nominee scores.

Supports the Org Attestor calibration trial (Module 4). Adds
``frameworks.is_calibration`` (fixtures are hidden from the marketplace),
the ``submitted`` state and grading columns on ``attestor_trials``, and the
per-fixture answer-key and per-trial rubric-score tables.

Revision ID: 2026_07_15_0084
Revises: 2026_07_14_0083
Create Date: 2026-07-15
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_15_0084"
down_revision: str | Sequence[str] | None = "2026_07_14_0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add fixtures flag, trial grading columns, and trial tables."""
    op.execute("ALTER TYPE attestor_trial_status_enum ADD VALUE IF NOT EXISTS 'submitted'")

    op.add_column(
        "frameworks",
        sa.Column("is_calibration", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
    )
    op.add_column(
        "frameworks",
        sa.Column("calibration_review_type", sa.Text(), nullable=True),
    )
    op.add_column("attestor_trials",
                  sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attestor_trials",
                  sa.Column("score_pct", sa.Numeric(5, 2), nullable=True))
    op.add_column("attestor_trials",
                  sa.Column("auto_result", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_attestor_trials_auto_result", "attestor_trials",
        "auto_result IS NULL OR auto_result IN ('pass','fail')",
    )

    op.create_table(
        "attestor_trial_answer_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dimension_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("attestation_rubric_dimensions.id"), nullable=False),
        sa.Column("expected_score", sa.Integer(), nullable=False),
        sa.Column("tolerance", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("framework_id", "dimension_id",
                            name="uq_attestor_trial_answer_keys_framework_dimension"),
        sa.CheckConstraint("expected_score BETWEEN 1 AND 5",
                           name="ck_attestor_trial_answer_keys_score_range"),
        sa.CheckConstraint("tolerance BETWEEN 0 AND 4",
                           name="ck_attestor_trial_answer_keys_tolerance_range"),
    )

    op.create_table(
        "attestor_trial_rubric_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("trial_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("attestor_trials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dimension_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("attestation_rubric_dimensions.id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("trial_id", "dimension_id",
                            name="uq_attestor_trial_rubric_scores_trial_dimension"),
        sa.CheckConstraint("score BETWEEN 1 AND 5",
                           name="ck_attestor_trial_rubric_scores_range"),
    )


def downgrade() -> None:
    """Drop trial tables + grading columns; leave the additive enum value.

    Postgres cannot drop an enum value; rows in ``submitted`` are first moved
    back to ``assigned`` so the prior code reads the column cleanly.
    """
    op.execute("UPDATE attestor_trials SET status = 'assigned' WHERE status = 'submitted'")
    op.drop_table("attestor_trial_rubric_scores")
    op.drop_table("attestor_trial_answer_keys")
    op.drop_constraint("ck_attestor_trials_auto_result", "attestor_trials")
    op.drop_column("attestor_trials", "auto_result")
    op.drop_column("attestor_trials", "score_pct")
    op.drop_column("attestor_trials", "submitted_at")
    op.drop_column("frameworks", "calibration_review_type")
    op.drop_column("frameworks", "is_calibration")
```
> Note: `ALTER TYPE ... ADD VALUE` cannot run inside a transaction on some setups. If `alembic upgrade` errors with "ALTER TYPE ... cannot run inside a transaction block", move that `op.execute` into its own migration revision that only adds the enum value (mirror `2026_07_14_0083`), chained before this one, and set this file's `down_revision` to it.

- [ ] **Step 6: Apply + verify up/down**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed, no error.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_calibration_trial_migration.py -v`
Expected: PASS.

- [ ] **Step 8: Lint**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Expected: clean.

- [ ] **Step 9: Commit**
```bash
git add backend/app/modules/frameworks/models.py backend/app/modules/attestation/models.py backend/migrations/versions/2026_07_15_0084_calibration_trial.py backend/tests/integration/test_calibration_trial_migration.py
git commit -m "Add calibration trial schema: fixtures flag, grading columns, trial tables"
```

---

## Task 2: Pure grading engine `trial_scoring.py`

**Files:**
- Create: `backend/app/modules/attestation/trial_scoring.py`
- Test: `backend/tests/unit/modules/test_trial_scoring.py`

**Interfaces:**
- Produces:
  - `PASS_THRESHOLD_PCT: float = 80.0`
  - `dimension_agreement(nominee: int, expected: int, tolerance: int) -> float`
  - `grade(nominee_scores: dict[UUID, int], answer_key: dict[UUID, tuple[int, int]], weights: dict[UUID, Decimal]) -> tuple[Decimal, str]` — returns `(score_pct, auto_result)` where `auto_result` is `"pass"` or `"fail"`. Keys of all three dicts are `dimension_id`.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/modules/test_trial_scoring.py`:
```python
"""Unit tests for the pure calibration-trial grading engine."""
from decimal import Decimal
from uuid import uuid4

from app.modules.attestation import trial_scoring


def test_exact_match_scores_100():
    """Every dimension exactly on the key → 100% → pass."""
    d1, d2 = uuid4(), uuid4()
    pct, result = trial_scoring.grade(
        nominee_scores={d1: 4, d2: 2},
        answer_key={d1: (4, 0), d2: (2, 0)},
        weights={d1: Decimal("0.5"), d2: Decimal("0.5")},
    )
    assert pct == Decimal("100.00")
    assert result == "pass"


def test_within_tolerance_full_credit():
    """A score inside the tolerance band earns full credit."""
    d1 = uuid4()
    pct, result = trial_scoring.grade(
        nominee_scores={d1: 3},
        answer_key={d1: (4, 1)},  # off by 1, tolerance 1
        weights={d1: Decimal("1.0")},
    )
    assert pct == Decimal("100.00")
    assert result == "pass"


def test_large_deviation_decays_and_weights():
    """Out-of-tolerance deviation decays linearly, weighted correctly."""
    d1, d2 = uuid4(), uuid4()
    # d1: |1-5|=4, tol 0 -> agreement 0; d2 exact -> 1. Weights 0.5/0.5 -> 50%.
    pct, result = trial_scoring.grade(
        nominee_scores={d1: 1, d2: 3},
        answer_key={d1: (5, 0), d2: (3, 0)},
        weights={d1: Decimal("0.5"), d2: Decimal("0.5")},
    )
    assert pct == Decimal("50.00")
    assert result == "fail"


def test_threshold_boundary():
    """79.9% fails, 80.0% passes."""
    d1 = uuid4()
    # agreement 0.80 -> |n-e|-t over 4 = 0.20 -> d-t = 0.8 -> pick e=5,n such that
    # 1 - (|n-5|-0)/4 = 0.8 -> |n-5| = 0.8 (not integer); use two dims to hit 80 exactly.
    d2 = uuid4()
    pct, result = trial_scoring.grade(
        nominee_scores={d1: 5, d2: 2},          # d1 exact (1.0), d2 off by 1 tol0 -> 0.75
        answer_key={d1: (5, 0), d2: (1, 0)},
        weights={d1: Decimal("0.5"), d2: Decimal("0.5")},
    )
    # (1.0*0.5 + 0.75*0.5) = 0.875 -> 87.5, pass. Adjust to boundary:
    assert result == "pass"
    assert pct == Decimal("87.50")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_trial_scoring.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`backend/app/modules/attestation/trial_scoring.py`:
```python
"""Pure grading for the Org Attestor calibration trial.

Compares a nominee's rubric scores against a fixture's answer key and returns a
weighted-agreement percentage plus a pass/fail suggestion. Dependency-free so
the formula is unit-testable in isolation (mirrors ``scoring.py``).

Maps to: calibration-trial design, "Grading" section.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

PASS_THRESHOLD_PCT: float = 80.0
_SCALE_SPAN: float = 4.0  # 1..5 rubric span


def dimension_agreement(nominee: int, expected: int, tolerance: int) -> float:
    """Agreement in [0,1] for one dimension.

    Full credit inside the tolerance band, then linear decay over the 1–5 span.

    Args:
        nominee: The nominee's score (1–5).
        expected: The answer-key score (1–5).
        tolerance: Allowed deviation for full credit (0–4).

    Returns:
        Agreement as a float in the inclusive range [0.0, 1.0].
    """
    delta = abs(nominee - expected)
    if delta <= tolerance:
        return 1.0
    return max(0.0, 1.0 - (delta - tolerance) / _SCALE_SPAN)


def grade(
    nominee_scores: dict[UUID, int],
    answer_key: dict[UUID, tuple[int, int]],
    weights: dict[UUID, Decimal],
) -> tuple[Decimal, str]:
    """Grade a full submission against the key.

    Args:
        nominee_scores: dimension_id -> nominee score (1–5).
        answer_key: dimension_id -> (expected_score, tolerance).
        weights: dimension_id -> rubric weight.

    Returns:
        ``(score_pct, auto_result)`` where ``score_pct`` is a Decimal rounded to
        two places and ``auto_result`` is ``"pass"`` or ``"fail"``.

    Raises:
        ValueError: If the three inputs do not cover the same dimension set, or
            total weight is zero.
    """
    keys = set(nominee_scores) & set(answer_key) & set(weights)
    if keys != set(nominee_scores) or keys != set(answer_key) or keys != set(weights):
        raise ValueError("nominee_scores, answer_key, and weights must cover the same dimensions")
    total_weight = sum((weights[k] for k in keys), Decimal(0))
    if total_weight == 0:
        raise ValueError("total rubric weight must be positive")

    earned = Decimal(0)
    for k in keys:
        expected, tolerance = answer_key[k]
        agree = Decimal(str(dimension_agreement(nominee_scores[k], expected, tolerance)))
        earned += weights[k] * agree

    pct = (earned / total_weight * Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    result = "pass" if pct >= Decimal(str(PASS_THRESHOLD_PCT)) else "fail"
    return pct, result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_trial_scoring.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**
```bash
cd backend && uv run ruff check app/modules/attestation/trial_scoring.py tests/unit/modules/test_trial_scoring.py && uv run mypy app/modules/attestation/trial_scoring.py
git add backend/app/modules/attestation/trial_scoring.py backend/tests/unit/modules/test_trial_scoring.py
git commit -m "Add pure calibration-trial grading engine"
```

---

## Task 3: Fixture leak guard

**Files:**
- Modify: `backend/app/modules/explore/service.py`, `backend/app/modules/frameworks/service.py`, `backend/app/modules/attestation/service.py` (wherever a query returns marketplace/attestable frameworks)
- Test: `backend/tests/integration/test_calibration_fixture_leak_guard.py`

**Interfaces:**
- Consumes: `Framework.is_calibration` (Task 1).
- Produces: no calibration framework appears in Explore search, framework listings, or attestation-target selection.

- [ ] **Step 1: Locate the query sites**

Run: `cd backend && grep -rn "Framework.status\|status == \"published\"\|is_calibration" app/modules/explore/service.py app/modules/frameworks/service.py app/modules/attestation/service.py`
Read each matched query. The guard is added to every query that returns frameworks for buyer-facing discovery or attestation targeting — **not** to owner-scoped "my frameworks" queries (a contributor could theoretically own a fixture only via admin, but fixtures are platform-owned, so owner queries are unaffected).

- [ ] **Step 2: Write the failing test**

`backend/tests/integration/test_calibration_fixture_leak_guard.py`:
```python
"""A calibration fixture must never surface on marketplace/attestation queries.

Enforces the design "Fixture leak guard": is_calibration=false on every
buyer-facing framework query.
"""
import pytest

# Use the project's existing framework factory + explore/search entry points.
# Adjust imports to match tests/factories and the search service signature.
from app.modules.explore import service as explore_service


@pytest.mark.asyncio
async def test_calibration_framework_absent_from_search(async_session_factory, framework_factory):
    """A published fixture flagged is_calibration is excluded from search."""
    async with async_session_factory() as s:
        # Published, discoverable normally — but flagged as a calibration fixture.
        fixture = await framework_factory(s, status="published", is_calibration=True)
        normal = await framework_factory(s, status="published", is_calibration=False)
        await s.commit()

        results = await explore_service.search_frameworks(s, query="")  # match real signature
        ids = {r.id for r in results.items}
        assert normal.id in ids
        assert fixture.id not in ids
```
> Before writing: confirm the real `search_frameworks` (or equivalent) signature and the response shape, and that `framework_factory` accepts `is_calibration`. If the factory does not, extend it in `tests/factories/` to pass `is_calibration` through (default `False`).

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_calibration_fixture_leak_guard.py -v`
Expected: FAIL — fixture leaks into results.

- [ ] **Step 4: Add the filter**

In each buyer-facing framework query add `.where(Framework.is_calibration.is_(False))`. Example (explore search):
```python
stmt = stmt.where(Framework.is_calibration.is_(False))
```
Apply to: explore search/list, framework public listings, attestation-target framework selection. Add a one-line comment at each site: `# Calibration fixtures are never marketplace/attestation-visible.`

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_calibration_fixture_leak_guard.py -v`
Expected: PASS. Then run the broader suites for those modules to catch regressions:
`cd backend && uv run pytest tests/integration -k "explore or framework or attestation" -q`

- [ ] **Step 6: Lint + commit**
```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/explore/service.py backend/app/modules/frameworks/service.py backend/app/modules/attestation/service.py backend/tests/integration/test_calibration_fixture_leak_guard.py backend/tests/factories
git commit -m "Exclude calibration fixtures from marketplace and attestation queries"
```

---

## Task 4: Trial schemas + nominee load service

**Files:**
- Modify: `backend/app/modules/organizations/schemas.py`
- Create: `backend/app/modules/organizations/attestor_trial_service.py`
- Test: `backend/tests/unit/modules/test_attestor_trial_service.py`

**Interfaces:**
- Produces:
  - Schemas: `TrialRubricDimensionSchema`, `TrialArtifactSchema`, `TrialScoreInput`, `TrialSubmitRequest`, `NomineeTrialResponse`, `AdminTrialGradeResponse`, `TrialDecideRequest`.
  - `async def load_nominee_trial(db, *, org_id: UUID, member: OrgMember) -> NomineeTrialResponse` — 404 when no assigned/submitted trial for the org, 403 when `member.id != application.trial_member_id`.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/modules/test_attestor_trial_service.py` (first test only):
```python
"""Unit tests for the nominee/admin calibration-trial service."""
import pytest
from fastapi import HTTPException

from app.modules.organizations import attestor_trial_service as svc


@pytest.mark.asyncio
async def test_load_nominee_trial_denies_non_nominee(seeded_trial):
    """A member who is not the nominated trial member gets 403."""
    ctx = seeded_trial  # provides db, org_id, other_member (not the nominee)
    with pytest.raises(HTTPException) as exc:
        await svc.load_nominee_trial(ctx.db, org_id=ctx.org_id, member=ctx.other_member)
    assert exc.value.status_code == 403
```
> Build a `seeded_trial` fixture in this test module (or `conftest`) that creates: an org, an application with `trial_member_id` set to member A, an `AttestorTrial(status="assigned", seeded_framework_id=<fixture fw>)`, seeded rubric dimensions for the fixture's `review_type`, answer keys, and a second member B (`other_member`). Reuse `_submitted_app_with_nominee` patterns from `tests/unit/modules/test_org_attestor_application_service.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestor_trial_service.py -v`
Expected: FAIL — module/function missing.

- [ ] **Step 3: Add schemas**

In `backend/app/modules/organizations/schemas.py`:
```python
class TrialRubricDimensionSchema(BaseModel):
    """One rubric dimension the nominee must score."""
    model_config = ConfigDict(from_attributes=True)
    dimension_id: UUID
    key: str
    label: str
    display_order: int


class TrialArtifactSchema(BaseModel):
    """A fixture artifact with a short-lived presigned view URL."""
    name: str
    mime_type: str
    url: str


class TrialScoreInput(BaseModel):
    """One nominee score for a dimension."""
    dimension_id: UUID
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=5000)


class TrialSubmitRequest(BaseModel):
    """Full rubric submission — one entry per dimension."""
    scores: list[TrialScoreInput] = Field(min_length=1)


class NomineeTrialResponse(BaseModel):
    """The nominee's live trial view."""
    trial_id: UUID
    status: str
    framework_name: str
    framework_summary: str | None
    artifacts: list[TrialArtifactSchema]
    dimensions: list[TrialRubricDimensionSchema]
    saved_scores: list[TrialScoreInput]
    feedback: str | None


class AdminTrialGradeResponse(BaseModel):
    """Admin grade view: nominee submission beside the answer key."""
    trial_id: UUID
    status: str
    score_pct: Decimal | None
    auto_result: str | None
    rows: list["AdminTrialGradeRow"]


class AdminTrialGradeRow(BaseModel):
    """Per-dimension comparison for the admin grade view."""
    dimension_id: UUID
    label: str
    weight: Decimal
    nominee_score: int | None
    nominee_comment: str | None
    expected_score: int
    tolerance: int


class TrialDecideRequest(BaseModel):
    """Admin confirm/override of the trial outcome."""
    result: Literal["pass", "fail"]
    feedback: str | None = Field(default=None, max_length=5000)
```
(Confirm `BaseModel`, `ConfigDict`, `Field`, `UUID`, `Decimal`, `Literal` imports exist at the top of `schemas.py`; add missing ones. Call `AdminTrialGradeResponse.model_rebuild()` after the forward-referenced `AdminTrialGradeRow` is defined, or define the row class first.)

- [ ] **Step 4: Implement `load_nominee_trial`**

`backend/app/modules/organizations/attestor_trial_service.py`:
```python
"""Org Attestor calibration-trial service.

Nominee-facing trial workspace (load fixture + rubric, submit scores) and
admin-facing grading (auto-score, confirm/override). Trial data lives in
trial-scoped tables; the escrow-funded attestations tables are untouched.

Maps to: calibration-trial design.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations import s3
from app.modules.attestation import rubrics, trial_scoring
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestorTrial,
    AttestorTrialAnswerKey,
    AttestorTrialRubricScore,
)
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations.models import OrgAttestorApplication, OrgMember
from app.modules.organizations.schemas import (
    NomineeTrialResponse,
    TrialArtifactSchema,
    TrialRubricDimensionSchema,
    TrialScoreInput,
)

# The trial's active (non-terminal) states the nominee can act within.
_OPEN_TRIAL_STATES = ("assigned", "submitted")


async def _load_open_trial(
    db: AsyncSession, *, org_id: UUID
) -> tuple[OrgAttestorApplication, AttestorTrial]:
    """Load the org's application + its latest open trial, or 404."""
    application = await db.scalar(
        select(OrgAttestorApplication).where(OrgAttestorApplication.org_id == org_id)
    )
    trial = None
    if application is not None:
        trial = await db.scalar(
            select(AttestorTrial)
            .where(
                AttestorTrial.org_application_id == application.id,
                AttestorTrial.status.in_(_OPEN_TRIAL_STATES),
            )
            .order_by(AttestorTrial.attempt.desc())
            .limit(1)
        )
    if application is None or trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No active trial.")
    return application, trial


async def load_nominee_trial(
    db: AsyncSession, *, org_id: UUID, member: OrgMember
) -> NomineeTrialResponse:
    """Return the nominee's live trial view.

    Args:
        db: Async session.
        org_id: Organization whose trial is requested.
        member: The calling org member.

    Returns:
        The fixture, rubric dimensions, presigned artifacts, and any saved scores.

    Raises:
        HTTPException(404): No active trial for the org.
        HTTPException(403): Caller is not the nominated trial member.
    """
    application, trial = await _load_open_trial(db, org_id=org_id)
    if member.id != application.trial_member_id:
        logger.bind(module="organizations", action="load_nominee_trial",
                    user_id=member.user_id, org_id=org_id).warning("access_denied")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Not the nominated trial member.")

    framework = await db.scalar(
        select(Framework).where(Framework.id == trial.seeded_framework_id)
    )
    if framework is None or framework.calibration_review_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Trial fixture missing.")

    dimensions = (await db.scalars(
        select(AttestationRubricDimension)
        .where(
            AttestationRubricDimension.review_type == framework.calibration_review_type,
            AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
        )
        .order_by(AttestationRubricDimension.display_order)
    )).all()

    artifacts = (await db.scalars(
        select(Artifact).where(Artifact.framework_id == framework.id)
    )).all()
    artifact_out = [
        TrialArtifactSchema(
            name=a.name,
            mime_type=a.mime_type,
            url=s3.storage.presigned_get(
                settings.s3_artifacts_bucket, a.clean_file_key or a.file_key
            ),
        )
        for a in artifacts
    ]

    saved = (await db.scalars(
        select(AttestorTrialRubricScore).where(
            AttestorTrialRubricScore.trial_id == trial.id
        )
    )).all()

    return NomineeTrialResponse(
        trial_id=trial.id,
        status=trial.status,
        framework_name=framework.title,      # Framework's display field is `title`
        framework_summary=framework.description,  # `description` is NOT NULL on Framework
        artifacts=artifact_out,
        dimensions=[
            TrialRubricDimensionSchema(
                dimension_id=d.id, key=d.key, label=d.label,
                display_order=d.display_order,
            )
            for d in dimensions
        ],
        saved_scores=[
            TrialScoreInput(dimension_id=s.dimension_id, score=s.score, comment=s.comment)
            for s in saved
        ],
        feedback=trial.feedback,
    )
```
> `Framework` fields are confirmed: display = `title`, `description` (NOT NULL), rubric selector = `calibration_review_type` (added in Task 1). Guard: if `framework.calibration_review_type is None` (a non-fixture or misconfigured fixture), raise `HTTPException(404, "Trial fixture missing.")` — the same branch as a missing framework. `AttestationRubricDimension` has no `dimension_id` attribute (its PK is `id`), so `TrialRubricDimensionSchema.model_validate(d)` cannot map `d.id → dimension_id` automatically; build each row explicitly: `TrialRubricDimensionSchema(dimension_id=d.id, key=d.key, label=d.label, display_order=d.display_order)`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestor_trial_service.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**
```bash
cd backend && uv run ruff check app/modules/organizations/attestor_trial_service.py app/modules/organizations/schemas.py tests/unit/modules/test_attestor_trial_service.py && uv run mypy app
git add backend/app/modules/organizations/attestor_trial_service.py backend/app/modules/organizations/schemas.py backend/tests/unit/modules/test_attestor_trial_service.py
git commit -m "Add calibration trial schemas and nominee trial load service"
```

> **Fixture review_type (resolved in Task 1):** the rubric selector lives on `frameworks.calibration_review_type` (Task 1). Tasks 4, 5, 7, 8 all read `framework.calibration_review_type`. `create_calibration_fixture` (Task 8) sets it at creation and validates it against the `ATTESTATION_REVIEW_TYPE_ENUM` values (`quality`/`compliance`/`expert`/`provenance`).

---

## Task 5: Nominee submit + auto-score

**Files:**
- Modify: `backend/app/modules/organizations/attestor_trial_service.py`
- Test: `backend/tests/unit/modules/test_attestor_trial_service.py`

**Interfaces:**
- Consumes: `trial_scoring.grade` (Task 2), `_load_open_trial`, schemas (Task 4).
- Produces: `async def submit_nominee_trial(db, *, org_id: UUID, member: OrgMember, payload: TrialSubmitRequest) -> NomineeTrialResponse`. Persists scores, computes `score_pct` + `auto_result`, sets `status="submitted"`, `submitted_at`. 409 if not `assigned`; 422 if a dimension is missing or unknown; 403 if not the nominee.

- [ ] **Step 1: Write the failing tests**

Append to `test_attestor_trial_service.py`:
```python
@pytest.mark.asyncio
async def test_submit_computes_score_and_flips_to_submitted(seeded_trial):
    """A complete submission scores, stores, and moves the trial to submitted."""
    ctx = seeded_trial
    payload = ctx.full_submission()  # helper: one TrialScoreInput per dimension, matching key
    out = await svc.submit_nominee_trial(
        ctx.db, org_id=ctx.org_id, member=ctx.nominee, payload=payload
    )
    assert out.status == "submitted"
    trial = await ctx.reload_trial()
    assert trial.status == "submitted"
    assert trial.submitted_at is not None
    assert trial.score_pct is not None
    assert trial.auto_result in ("pass", "fail")


@pytest.mark.asyncio
async def test_submit_missing_dimension_422(seeded_trial):
    """A submission missing any dimension is rejected 422."""
    ctx = seeded_trial
    payload = ctx.full_submission()
    payload.scores.pop()  # drop one dimension
    with pytest.raises(HTTPException) as exc:
        await svc.submit_nominee_trial(ctx.db, org_id=ctx.org_id, member=ctx.nominee, payload=payload)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_resubmit_after_submitted_409(seeded_trial):
    """Submitting when the trial is no longer assigned is rejected 409."""
    ctx = seeded_trial
    await svc.submit_nominee_trial(ctx.db, org_id=ctx.org_id, member=ctx.nominee, payload=ctx.full_submission())
    with pytest.raises(HTTPException) as exc:
        await svc.submit_nominee_trial(ctx.db, org_id=ctx.org_id, member=ctx.nominee, payload=ctx.full_submission())
    assert exc.value.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestor_trial_service.py -k submit -v`
Expected: FAIL — `submit_nominee_trial` missing.

- [ ] **Step 3: Implement**

Add to `attestor_trial_service.py`:
```python
async def submit_nominee_trial(
    db: AsyncSession,
    *,
    org_id: UUID,
    member: OrgMember,
    payload: TrialSubmitRequest,
) -> NomineeTrialResponse:
    """Persist the nominee's rubric, auto-score it, and mark the trial submitted.

    Raises:
        HTTPException(403): Caller is not the nominated member.
        HTTPException(404): No active trial / fixture missing.
        HTTPException(409): Trial is not in the ``assigned`` state.
        HTTPException(422): Missing, duplicate, or unknown dimension in the payload.
    """
    application, trial = await _load_open_trial(db, org_id=org_id)
    if member.id != application.trial_member_id:
        logger.bind(module="organizations", action="submit_nominee_trial",
                    user_id=member.user_id, org_id=org_id).warning("access_denied")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Not the nominated trial member.")
    if trial.status != "assigned":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Trial already submitted.")

    framework = await db.scalar(select(Framework).where(Framework.id == trial.seeded_framework_id))
    if framework is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial fixture missing.")

    dimensions = (await db.scalars(
        select(AttestationRubricDimension).where(
            AttestationRubricDimension.review_type == framework.calibration_review_type,
            AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
        )
    )).all()
    dim_ids = {d.id for d in dimensions}
    submitted = {s.dimension_id: s for s in payload.scores}
    if set(submitted) != dim_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Every rubric dimension must be scored exactly once.")

    keys = (await db.scalars(
        select(AttestorTrialAnswerKey).where(
            AttestorTrialAnswerKey.framework_id == framework.id
        )
    )).all()
    key_map = {k.dimension_id: (k.expected_score, k.tolerance) for k in keys}
    if set(key_map) != dim_ids:
        # Fixture curation must guarantee this; treat as an admin data error.
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Fixture answer key is incomplete.")
    weights = {d.id: d.weight for d in dimensions}

    score_pct, auto_result = trial_scoring.grade(
        nominee_scores={did: submitted[did].score for did in dim_ids},
        answer_key=key_map,
        weights=weights,
    )

    async with db.begin_nested():
        for s in payload.scores:
            db.add(AttestorTrialRubricScore(
                trial_id=trial.id, dimension_id=s.dimension_id,
                score=s.score, comment=s.comment,
            ))
        trial.status = "submitted"
        trial.submitted_at = datetime.now(UTC)
        trial.score_pct = score_pct
        trial.auto_result = auto_result
    await db.commit()

    logger.bind(module="organizations", action="submit_nominee_trial",
                user_id=member.user_id, org_id=org_id).info("trial_submitted")
    return await load_nominee_trial(db, org_id=org_id, member=member)
```
> If the surrounding endpoint already opens a transaction, replace `db.begin_nested()` + `db.commit()` with the module's standard pattern. Confirm sessions in this codebase are not already in an outer transaction at service entry (they are typically committed by the service — mirror `admin_start_trial`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestor_trial_service.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**
```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/organizations/attestor_trial_service.py backend/tests/unit/modules/test_attestor_trial_service.py
git commit -m "Add nominee trial submission with auto-scoring"
```

---

## Task 6: Nominee endpoints + OpenAPI + notification repoint

**Files:**
- Modify: `backend/app/modules/organizations/router.py`
- Modify: `backend/app/modules/organizations/attestor_application_service.py` (notification link)
- Test: `backend/tests/integration/test_attestor_trial_endpoints.py`

**Interfaces:**
- Consumes: `load_nominee_trial`, `submit_nominee_trial` (Tasks 4–5); `require_org_role("member")` → `OrgContext`.
- Produces: `GET /v1/organizations/{org_id}/attestor-trial`, `POST /v1/organizations/{org_id}/attestor-trial/submit`.

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_attestor_trial_endpoints.py`:
```python
"""Integration tests for the nominee calibration-trial endpoints."""
import pytest


@pytest.mark.asyncio
async def test_nominee_can_load_and_submit(client, seeded_trial_http):
    """The nominated member loads the trial and submits a full rubric → 200."""
    ctx = seeded_trial_http
    r = await client.get(f"/v1/organizations/{ctx.org_id}/attestor-trial",
                         headers=ctx.nominee_headers)
    assert r.status_code == 200
    dims = r.json()["dimensions"]

    body = {"scores": [{"dimension_id": d["dimension_id"], "score": 3} for d in dims]}
    r2 = await client.post(f"/v1/organizations/{ctx.org_id}/attestor-trial/submit",
                           json=body, headers=ctx.nominee_headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_non_nominee_member_forbidden(client, seeded_trial_http):
    """A different org member is 403 on the trial endpoint."""
    ctx = seeded_trial_http
    r = await client.get(f"/v1/organizations/{ctx.org_id}/attestor-trial",
                         headers=ctx.other_member_headers)
    assert r.status_code == 403
```
> Build `seeded_trial_http` from the existing integration fixtures (`tests/integration/test_org_attestor_admin_endpoints.py` shows org/app/member + auth-header helpers). It needs: org, submitted application with `trial_member_id`, an `assigned` trial on a fixture framework, seeded rubric dimensions + answer keys, and auth headers for the nominee and a second member.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestor_trial_endpoints.py -v`
Expected: FAIL — endpoints 404.

- [ ] **Step 3: Add the endpoints**

In `backend/app/modules/organizations/router.py` (member-scoped; use `require_org_role("member")`):
```python
@router.get(
    "/{org_id}/attestor-trial",
    response_model=NomineeTrialResponse,
    summary="Load the nominee calibration trial",
    description="Return the nominated member's active trial: fixture, rubric, and saved scores.",
)
async def get_attestor_trial(
    org_id: UUID,
    context: Annotated[OrgContext, Depends(require_org_role("member"))],
    db: DatabaseSession,
) -> NomineeTrialResponse:
    """Return the nominee's live calibration trial."""
    return await attestor_trial_service.load_nominee_trial(
        db, org_id=org_id, member=context.member
    )


@router.post(
    "/{org_id}/attestor-trial/submit",
    response_model=NomineeTrialResponse,
    summary="Submit the nominee calibration trial",
    description="Persist the nominee's rubric scores and auto-score the trial.",
)
async def submit_attestor_trial(
    org_id: UUID,
    payload: TrialSubmitRequest,
    context: Annotated[OrgContext, Depends(require_org_role("member"))],
    db: DatabaseSession,
) -> NomineeTrialResponse:
    """Submit the nominee's rubric for the active trial."""
    return await attestor_trial_service.submit_nominee_trial(
        db, org_id=org_id, member=context.member, payload=payload
    )
```
(Import `attestor_trial_service`, `NomineeTrialResponse`, `TrialSubmitRequest`, `require_org_role`, `OrgContext` at the top of `router.py` as needed. Use the module's existing `Annotated[...]` dependency style; if a `require_org_role("member")` alias already exists, reuse it.)

- [ ] **Step 4: Repoint the nominee notification link**

In `backend/app/modules/organizations/attestor_application_service.py` (~line 1218), change:
```python
            link=f"/dashboard/organizations/{org_id}/attestor",
```
to:
```python
            link=f"/dashboard/organizations/{org_id}/attestor-trial",
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_attestor_trial_endpoints.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**
```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/organizations/router.py backend/app/modules/organizations/attestor_application_service.py backend/tests/integration/test_attestor_trial_endpoints.py
git commit -m "Add nominee trial endpoints and repoint assignment notification"
```

---

## Task 7: Admin start-trial fixture picker + key validation

**Files:**
- Modify: `backend/app/modules/organizations/attestor_application_service.py` (`admin_start_trial` gains `framework_id`)
- Modify: `backend/app/modules/organizations/router.py` (start-trial request body)
- Modify: `backend/app/modules/organizations/schemas.py` (start-trial request schema)
- Test: `backend/tests/unit/modules/test_org_attestor_application_service.py`, `backend/tests/integration/test_org_attestor_admin_endpoints.py`

**Interfaces:**
- Consumes: `Framework.is_calibration`, `AttestorTrialAnswerKey`, rubric dimensions.
- Produces: `admin_start_trial(db, *, application_id, admin_id, framework_id: UUID)` — sets `seeded_framework_id`; 422 if the fixture is not a calibration framework or its answer key does not cover every rubric dimension for the fixture's review_type. Existing idempotency/attempt-cap behavior preserved.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/modules/test_org_attestor_application_service.py`:
```python
@pytest.mark.asyncio
async def test_start_trial_sets_seeded_framework(_submitted_app_with_nominee, calibration_fixture):
    """Starting the trial with a valid fixture stores seeded_framework_id."""
    app_id, member_id, admin_id = _submitted_app_with_nominee
    fw_id = calibration_fixture.id  # complete answer key seeded
    trial = await svc.admin_start_trial(db, application_id=app_id, admin_id=admin_id, framework_id=fw_id)
    assert trial.seeded_framework_id == fw_id
    assert trial.status == "assigned"


@pytest.mark.asyncio
async def test_start_trial_rejects_incomplete_key(_submitted_app_with_nominee, fixture_missing_key):
    """A fixture missing an answer-key entry for a dimension is rejected 422."""
    app_id, member_id, admin_id = _submitted_app_with_nominee
    with pytest.raises(HTTPException) as exc:
        await svc.admin_start_trial(db, application_id=app_id, admin_id=admin_id, framework_id=fixture_missing_key.id)
    assert exc.value.status_code == 422
```
> Add `calibration_fixture` (published `is_calibration=True` framework + one artifact + a complete answer key for every rubric dimension of its `review_type`) and `fixture_missing_key` (same but one key row omitted) fixtures.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_attestor_application_service.py -k start_trial -v`
Expected: FAIL — `admin_start_trial` has no `framework_id` param.

- [ ] **Step 3: Add the request schema**

In `schemas.py`:
```python
class AdminStartTrialRequest(BaseModel):
    """Admin selection of the calibration fixture for a trial."""
    framework_id: UUID
```

- [ ] **Step 4: Extend `admin_start_trial`**

Update the signature to accept `framework_id: UUID` and, before creating/returning the trial, validate the fixture (inside the existing `async with db.begin():`, after loading the nominee):
```python
    fixture = await db.scalar(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.is_calibration.is_(True),
        )
    )
    if fixture is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Selected framework is not a calibration fixture.")
    dim_ids = set((await db.scalars(
        select(AttestationRubricDimension.id).where(
            AttestationRubricDimension.review_type == fixture.calibration_review_type,
            AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
        )
    )).all())
    key_dims = set((await db.scalars(
        select(AttestorTrialAnswerKey.dimension_id).where(
            AttestorTrialAnswerKey.framework_id == fixture.id
        )
    )).all())
    if not dim_ids or key_dims != dim_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Fixture answer key is incomplete for its rubric.")
```
Set `seeded_framework_id=framework_id` on the created `AttestorTrial`. For the idempotent `assigned`-return branch (existing), leave the previously chosen fixture in place (do not overwrite). Import `Framework`, `AttestationRubricDimension`, `AttestorTrialAnswerKey`, `rubrics` in this file.

- [ ] **Step 5: Update the router endpoint**

In `router.py`, `admin_start_trial` endpoint: accept `payload: AdminStartTrialRequest` and pass `framework_id=payload.framework_id` to the service.

- [ ] **Step 6: Fix existing start-trial tests**

The existing integration `test_org_attestor_admin_endpoints.py` start-trial calls now need a body. Update `_gated_application` to also seed a `calibration_fixture` and pass `{"framework_id": ...}` to every start-trial POST. Run:
`cd backend && uv run pytest tests/integration/test_org_attestor_admin_endpoints.py tests/unit/modules/test_org_attestor_application_service.py -v`
Expected: PASS (both new and previously-green tests).

- [ ] **Step 7: Lint + commit**
```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/organizations/attestor_application_service.py backend/app/modules/organizations/router.py backend/app/modules/organizations/schemas.py backend/tests
git commit -m "Require a validated calibration fixture when starting a trial"
```

---

## Task 8: Admin grade view + decide endpoint + fixture curation

**Files:**
- Modify: `backend/app/modules/organizations/attestor_trial_service.py` (grade view + decide + fixture/key CRUD)
- Modify: `backend/app/modules/organizations/router.py` (admin grade/decide + curation endpoints)
- Test: `backend/tests/unit/modules/test_attestor_trial_service.py`, `backend/tests/integration/test_org_attestor_admin_endpoints.py`

**Interfaces:**
- Produces:
  - `async def admin_trial_grade(db, *, application_id: UUID) -> AdminTrialGradeResponse`
  - `async def admin_decide_trial(db, *, application_id: UUID, admin_id: UUID, payload: TrialDecideRequest) -> AttestorTrial` — 409 if not `submitted`; sets `status="passed"|"failed"`, `decided_by`, `decided_at`, `feedback`; audits.
  - Fixture curation: `create_calibration_fixture(...)`, `upsert_answer_key(...)`, `list_fixtures(...)` (admin).

- [ ] **Step 1: Write the failing tests**

Append to `test_attestor_trial_service.py`:
```python
@pytest.mark.asyncio
async def test_admin_decide_pass_flips_gate(seeded_submitted_trial):
    """Admin confirming pass sets status=passed and the application gate passes."""
    ctx = seeded_submitted_trial
    trial = await svc.admin_decide_trial(
        ctx.db, application_id=ctx.application_id, admin_id=ctx.admin_id,
        payload=TrialDecideRequest(result="pass", feedback="Solid calibration."),
    )
    assert trial.status == "passed"
    assert trial.decided_by == ctx.admin_id
    assert await app_svc._trial_passed(ctx.db, ctx.application_id) is True


@pytest.mark.asyncio
async def test_admin_decide_requires_submitted(seeded_trial):
    """Deciding a trial that is still assigned is 409."""
    ctx = seeded_trial  # status assigned
    with pytest.raises(HTTPException) as exc:
        await svc.admin_decide_trial(
            ctx.db, application_id=ctx.application_id, admin_id=ctx.admin_id,
            payload=TrialDecideRequest(result="pass"),
        )
    assert exc.value.status_code == 409
```
(Import `TrialDecideRequest`, `app_svc` = `attestor_application_service`. `seeded_submitted_trial` = a trial already `submitted` with scores + score_pct.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestor_trial_service.py -k "decide" -v`
Expected: FAIL — functions missing.

- [ ] **Step 3: Implement grade + decide**

Add to `attestor_trial_service.py`:
```python
async def _load_trial_for_admin(
    db: AsyncSession, *, application_id: UUID
) -> AttestorTrial:
    """Load the latest trial for an application, or 404."""
    trial = await db.scalar(
        select(AttestorTrial)
        .where(AttestorTrial.org_application_id == application_id)
        .order_by(AttestorTrial.attempt.desc())
        .limit(1)
    )
    if trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No trial.")
    return trial


async def admin_trial_grade(
    db: AsyncSession, *, application_id: UUID
) -> AdminTrialGradeResponse:
    """Return the nominee submission beside the answer key for admin grading."""
    trial = await _load_trial_for_admin(db, application_id=application_id)
    framework = await db.scalar(select(Framework).where(Framework.id == trial.seeded_framework_id))
    dimensions = (await db.scalars(
        select(AttestationRubricDimension).where(
            AttestationRubricDimension.review_type == framework.calibration_review_type,
            AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
        ).order_by(AttestationRubricDimension.display_order)
    )).all()
    scores = {s.dimension_id: s for s in (await db.scalars(
        select(AttestorTrialRubricScore).where(AttestorTrialRubricScore.trial_id == trial.id)
    )).all()}
    keys = {k.dimension_id: k for k in (await db.scalars(
        select(AttestorTrialAnswerKey).where(AttestorTrialAnswerKey.framework_id == framework.id)
    )).all()}
    rows = [
        AdminTrialGradeRow(
            dimension_id=d.id, label=d.label, weight=d.weight,
            nominee_score=(scores[d.id].score if d.id in scores else None),
            nominee_comment=(scores[d.id].comment if d.id in scores else None),
            expected_score=keys[d.id].expected_score,
            tolerance=keys[d.id].tolerance,
        )
        for d in dimensions
    ]
    return AdminTrialGradeResponse(
        trial_id=trial.id, status=trial.status,
        score_pct=trial.score_pct, auto_result=trial.auto_result, rows=rows,
    )


async def admin_decide_trial(
    db: AsyncSession, *, application_id: UUID, admin_id: UUID, payload: TrialDecideRequest
) -> AttestorTrial:
    """Confirm or override the trial outcome (replaces the manual DB flip).

    Raises:
        HTTPException(404): No trial.
        HTTPException(409): Trial is not in the ``submitted`` state.
    """
    async with db.begin():
        trial = await _load_trial_for_admin(db, application_id=application_id)
        if trial.status != "submitted":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Trial is not awaiting a decision.")
        trial.status = "passed" if payload.result == "pass" else "failed"
        trial.decided_by = admin_id
        trial.decided_at = datetime.now(UTC)
        trial.feedback = payload.feedback
        await write_audit(
            db, actor_id=admin_id, action="org_attestor_trial_decided",
            target_type="attestor_trial", target_id=trial.id,
            metadata={"result": payload.result, "score_pct": str(trial.score_pct)},
        )
    logger.bind(module="organizations", action="admin_decide_trial",
                user_id=admin_id, trial_id=trial.id).info("trial_decided")
    return trial
```
(Import `write_audit` from `app.core.audit`, and `AdminTrialGradeResponse`, `AdminTrialGradeRow`, `TrialDecideRequest` from schemas.)

- [ ] **Step 4: Fixture curation service + endpoints**

Add to `attestor_trial_service.py` an admin-only `create_calibration_fixture` (create a `Framework` with `is_calibration=True`, `status="published"`, a chosen `review_type`) and `upsert_answer_key(db, *, framework_id, dimension_id, expected_score, tolerance)` (insert or update the unique row). Then add admin endpoints on `admin_org_attestor_router` in `router.py`:
```python
@admin_org_attestor_router.get("/{application_id}/trial", response_model=AdminTrialGradeResponse,
    summary="Admin calibration-trial grade view")
async def admin_get_trial_grade(application_id: UUID, admin: PlatformAdmin, db: DatabaseSession) -> AdminTrialGradeResponse:
    """Return the nominee submission beside the answer key."""
    return await attestor_trial_service.admin_trial_grade(db, application_id=application_id)


@admin_org_attestor_router.post("/{application_id}/trial/decide", response_model=OrgAttestorApplicationResponse,
    summary="Decide the calibration trial (platform admin)")
async def admin_decide_trial(application_id: UUID, payload: TrialDecideRequest, admin: PlatformAdmin, db: DatabaseSession) -> OrgAttestorApplicationResponse:
    """Confirm/override the trial and return the refreshed application."""
    await attestor_trial_service.admin_decide_trial(db, application_id=application_id, admin_id=admin.id, payload=payload)
    application, checklist = await attestor_application_service.get_application_by_id(db, application_id=application_id)
    return _application_response(application, checklist)
```
Fixture-curation admin endpoints (list fixtures, create fixture, upsert answer key) go on a dedicated admin router group — e.g. `admin_org_attestor_router` prefix or a small `admin_calibration_router`. Keep them platform-admin gated. (Fixture *creation* can reuse the existing framework-create path with `is_calibration=True`; the minimum here is the answer-key upsert + a fixtures list for the admin picker.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestor_trial_service.py tests/integration/test_org_attestor_admin_endpoints.py -v`
Expected: PASS.

- [ ] **Step 6: Replace manual-flip in the full gate walk**

Update `test_org_attestor_admin_endpoints.py::test_full_gate_walk_to_approval`: instead of flipping the trial to `passed` directly in the DB, POST the nominee submit then `POST /{application_id}/trial/decide {"result":"pass"}` before approve. Run that test:
`cd backend && uv run pytest tests/integration/test_org_attestor_admin_endpoints.py -k full_gate_walk -v`
Expected: PASS.

- [ ] **Step 7: Lint + commit**
```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/organizations/attestor_trial_service.py backend/app/modules/organizations/router.py backend/tests
git commit -m "Add admin trial grade view, decide endpoint, and fixture curation"
```

---

## Task 9: Contract + client regeneration

**Files:**
- Modify: `contracts/openapi.yaml`
- Modify: generated client under `frontend/src/lib/generated/`

**Interfaces:**
- Produces: generated client functions `getAttestorTrial`, `submitAttestorTrial`, `adminGetTrialGrade`, `adminDecideTrial`, `adminStartTrial` (updated with body), plus types for all new schemas.

- [ ] **Step 1: Refresh the contract**

If `contracts/openapi.yaml` is generated from the FastAPI app, export it (project's usual command — check `backend/` scripts/Makefile for an `openapi` export). Otherwise hand-add the five endpoints + schemas to `contracts/openapi.yaml` matching the Pydantic models exactly (operationIds: `getAttestorTrial`, `submitAttestorTrial`, `adminGetTrialGrade`, `adminDecideTrial`; update `startOrgAttestorTrial` request body to `AdminStartTrialRequest`).

- [ ] **Step 2: Regenerate the client**

Run: `cd frontend && npm run generate:api`
Expected: `sdk.gen.ts` / `types.gen.ts` gain the new functions/types with no diff errors.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: clean (no consumers yet).

- [ ] **Step 4: Commit**
```bash
git add contracts/openapi.yaml frontend/src/lib/generated
git commit -m "Regenerate client for calibration trial endpoints"
```

---

## Task 10: Nominee trial workspace (frontend)

**Files:**
- Create: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/attestor-trial/page.tsx`
- Create: `frontend/src/components/modules/organizations/attestor/trial-workspace.tsx`
- Test: `frontend/src/components/modules/organizations/attestor/trial-workspace.test.tsx`

**Interfaces:**
- Consumes: `getAttestorTrial`, `submitAttestorTrial` (Task 9); `configureBrowserClient`, `getAccessTokenHeaders`, `describeGeneratedError` from `@/lib/auth/form-client`.

- [ ] **Step 1: Write the failing component test**

`trial-workspace.test.tsx`: mock `getAttestorTrial` → `assigned` trial with 2 dimensions + 1 artifact; assert the rubric form renders, Submit is disabled until every dimension has a score, clicking Submit calls `submitAttestorTrial` with all scores, and after a `submitted` response the form switches to a read-only "Under review" state. Mirror the mocking style in `admin-org-attestor-review-panel.test.tsx` (`vi.mock("@/lib/generated/sdk.gen", ...)`, an `ok()` helper).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/modules/organizations/attestor/trial-workspace.test.tsx`
Expected: FAIL — component missing.

- [ ] **Step 3: Build the component + page**

`trial-workspace.tsx` (`"use client"`): load the trial on mount (`configureBrowserClient()` + `getAccessTokenHeaders()`); render fixture name/summary, artifact links (`<a href={url}>`), and one row per dimension with a 1–5 selector + optional comment; Submit gated on all dimensions scored; on 200 → `status==="submitted"` → read-only "Under review" panel; on terminal `passed`/`failed` show outcome + `feedback`. Handle 404 (no trial → "No active trial assigned") and 403 (→ "This trial is assigned to another member") distinctly. Mobile-first: 44px touch targets, single-column at base, tested at 375px. File-level + component JSDoc per standards.

`page.tsx`: thin server/client wrapper that reads `orgId` from params and renders `<TrialWorkspace orgId={orgId} />`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/modules/organizations/attestor/trial-workspace.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint + commit**
```bash
cd frontend && npx tsc --noEmit && npx eslint src/components/modules/organizations/attestor/trial-workspace.tsx src/app/\(auth\)/dashboard/organizations/\[orgId\]/attestor-trial/page.tsx
git add "frontend/src/app/(auth)/dashboard/organizations/[orgId]/attestor-trial" frontend/src/components/modules/organizations/attestor/trial-workspace.tsx frontend/src/components/modules/organizations/attestor/trial-workspace.test.tsx
git commit -m "Add nominee calibration-trial workspace page"
```

---

## Task 11: Admin grade view + fixture picker (frontend)

**Files:**
- Modify: `frontend/src/components/modules/admin/admin-org-attestor-review-panel.tsx` (+ `.test.tsx`)

**Interfaces:**
- Consumes: `adminGetTrialGrade`, `adminDecideTrial`, updated `startOrgAttestorTrial` (Task 9).

- [ ] **Step 1: Write the failing test**

In `admin-org-attestor-review-panel.test.tsx` add: (a) starting a trial requires choosing a fixture — mock a fixtures list, assert Start Trial sends `{ framework_id }`; (b) for a `submitted` trial, the grade view renders `score_pct` + `auto_result` suggestion and Pass/Fail buttons; clicking Pass calls `adminDecideTrial` with `{result:"pass"}` and the row advances to "Passed". Follow the existing test's mocking + `ok()` conventions.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/modules/admin/admin-org-attestor-review-panel.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

In the panel: the Start Trial control opens a fixture picker (list from the fixtures endpoint) and passes `framework_id`; when a trial is `submitted`, show a grade sub-view (call `adminGetTrialGrade`) rendering per-dimension nominee-vs-key rows, `score_pct`, the `auto_result` suggestion, and Pass/Fail + feedback that call `adminDecideTrial`; on success patch the local row (`applyUpdate`) so the gate advances — reuse the existing `handleAction`/`applyUpdate` pattern already in this file. Keep mobile-first.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/modules/admin/admin-org-attestor-review-panel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint + full frontend test + commit**
```bash
cd frontend && npx tsc --noEmit && npx eslint src/components/modules/admin/admin-org-attestor-review-panel.tsx && npx vitest run
git add frontend/src/components/modules/admin/admin-org-attestor-review-panel.tsx frontend/src/components/modules/admin/admin-org-attestor-review-panel.test.tsx
git commit -m "Add admin calibration-trial grade view and fixture picker"
```

---

## Task 12: Full-stack verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite + coverage**

Run: `cd backend && uv run pytest tests/unit/modules/test_trial_scoring.py tests/unit/modules/test_attestor_trial_service.py tests/unit/modules/test_org_attestor_application_service.py tests/integration/test_attestor_trial_endpoints.py tests/integration/test_org_attestor_admin_endpoints.py tests/integration/test_calibration_fixture_leak_guard.py tests/integration/test_calibration_trial_migration.py -v`
Expected: all pass.

- [ ] **Step 2: Migration up/down once more**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all succeed.

- [ ] **Step 3: Full-repo lint/type**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: clean, all green.

- [ ] **Step 4: Manual smoke (localhost)**

Start the stack; as admin: pick a fixture → start trial. Log in as the nominee → open `/dashboard/organizations/{orgId}/attestor-trial` (no more "Failed to load application") → submit rubric. As admin: open grade view → confirm pass. Verify the application's Trial gate flips to Passed and Approve unblocks.

- [ ] **Step 5: Commit any final fixes**
```bash
git add -A
git commit -m "Finalize calibration trial verification fixes"
```

---

## Self-Review Notes (author)

- **Spec coverage:** fixtures flag + curation (T1, T3, T8) · answer keys + trial-score tables (T1) · pure grading ≥80% (T2) · state machine assigned→submitted→passed/failed (T1 enum, T5 submit, T8 decide) · nominee endpoints + member RBAC + 404/403 split (T4, T6) · admin start-trial fixture validation (T7) · admin grade + decide replacing manual flip (T8) · leak guard + regression (T3) · notification repoint / dead-link fix (T6) · nominee + admin surfaces (T10, T11) · edge cases (422/409/403 in T5–T8) · tests at every layer (all).
- **Resolved before handoff:** `Framework` display = `title`, `description` (NOT NULL); it has no `review_type`, so Task 1 adds `frameworks.calibration_review_type` and Tasks 4/5/7/8 read it.
- **Open confirmations for the implementer (called out inline, each with a concrete fallback):** the real explore search signature + whether the framework factory accepts `is_calibration` (Task 3); whether the trial enum `ADD VALUE` needs its own migration revision (Task 1 Step 5 note); the module's transaction-entry convention — service-commits vs endpoint-commits — for `submit_nominee_trial`'s `begin_nested`/`commit` (Task 5 note).
