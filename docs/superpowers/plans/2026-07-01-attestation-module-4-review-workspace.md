# Attestation Module 4 — Review Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current one-shot attestation report POST into a persistent, structured Review Workspace — rubric scoring, free-anchor annotations, clarification requests with SLA pause, and an automated submission quality gate — extending the existing report/PDF flow in place.

**Architecture:** Additive backend slices on the existing `attestation` module. New working status `in_review` sits between `accepted` and `report_submitted`. New child tables (rubric dimensions/methodology seeded, rubric scores, annotations, clarifications) hang off `attestations`. The existing `report.submit_report` becomes the gated commit point; the existing WeasyPrint renderer grows to eight sections. The Module 3 revoke-beat widens to cover `in_review` + a grace window.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, PostgreSQL 16, Celery + Beat, WeasyPrint, loguru, pytest + pytest-asyncio, `uv`. All backend commands run from `backend/`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-01-attestation-module-4-review-workspace-design.md` — source of truth for every value below.
- Migration head before this work: `2026_06_30_0047`. New migrations chain from it in date order `2026_07_01_00NN`.
- Enum `ALTER TYPE ... ADD VALUE` runs inside `op.get_context().autocommit_block()` with `ADD VALUE IF NOT EXISTS` (precedent: `migrations/versions/2026_06_29_0041_attestor_onboarding.py`).
- Rubric weights per review_type sum to **exactly 1.000**. Weighted overall = `Σ(weight × score)`, score 1–5, result in [1.00, 5.00], stored `numeric(3,2)`.
- Config defaults (via `PlatformConfig`, integer helper `_platform_int_config`): `attestation_clarification_response_hours`=48, `attestation_completion_grace_hours`=24, `attestation_report_min_words`=150. Boolean gate `attestation_report_block_contact_info` default on (stored `"1"`/`"0"`).
- RBAC at the FastAPI dependency layer only. New workspace endpoints: assigned-Attestor-only, **404** on mismatch (hide existence). Clarification-respond: **Requestor-only**.
- Audit metadata: ids, counts, enums, booleans, numbers only — never PII/secrets/report text. Use `app.core.audit.write_audit`.
- No secrets in code/logs. Presigned artifact delivery only (Module 2b) — never proxy files.
- Money/escrow untouched. `report_submitted` stays the sole Module 5 trigger. Dispute-window logic unchanged.
- Every schema change = one Alembic migration; `alembic upgrade head` and `downgrade -1` must both succeed.
- All logging via `loguru` with `module="attestation"` + snake_case `action`.
- Whole-repo gates before any slice is claimed done: `uv run pytest <slice test files>`, `uv run ruff check .`, `uv run mypy app` — all green.
- Commit messages end at the last meaningful line — no `Co-Authored-By`/generated trailer. Work on `main`.
- Google-style docstrings on every new module/class/public function (CLAUDE.md). Each public router endpoint gets an OpenAPI summary + docstring.

---

## File Structure

**Create:**
- `app/modules/attestation/rubrics.py` — rubric constants (all 4 types), weight-sum guard, weighted-overall helper, canned methodology text.
- `app/modules/attestation/workspace_service.py` — `start_review`, rubric-score upsert, annotation CRUD, and the shared 404 assigned-Attestor loader for Module 4 endpoints.
- `app/modules/attestation/clarification_service.py` — send / respond / expire clarifications + SLA-pause math.
- `tests/unit/modules/test_attestation_rubrics.py`
- `tests/unit/modules/test_attestation_workspace.py`
- `tests/unit/modules/test_attestation_clarifications.py`
- `tests/unit/modules/test_attestation_quality_gate.py`
- `tests/integration/test_attestation_workspace.py`
- `tests/integration/test_attestation_clarifications.py`
- `tests/unit/workers/test_attestation_clarification_expiry.py`
- Migrations: `2026_07_01_0048_*`, `2026_07_01_0049_*` (see tasks).

**Modify:**
- `app/modules/attestation/models.py` — new enum objects, columns on `Attestation`/`AttestorProfile`, tables `AttestationRubricDimension`, `AttestationRubricMethodology`, `AttestationRubricScore`, `AttestationAnnotation`, `AttestationClarification`.
- `app/modules/attestation/schemas.py` — workspace + clarification + extended-submit request/response schemas.
- `app/modules/attestation/router.py` — new endpoints.
- `app/modules/attestation/report.py` — gated submit (conditions, late-stamp, rubric_version, precondition `in_review`).
- `app/modules/attestation/matching_service.py` — widen `revoke_overdue_attestations` to `{accepted, in_review}` + grace window.
- `app/workers/tasks/attestation_beat.py` + `app/workers/beat_schedule.py` — `expire_attestation_clarifications` beat.
- `app/workers/tasks/attestation_pdf.py` — eight-section template + expanded data load.
- `contracts/openapi.yaml` — new endpoints (folded into the slice that adds each).

**Reuse unchanged:** `access_service.request_artifact_access` (left-panel viewer), `render_attestation_report_pdf` dispatch, `dispatch_project_notification`, Module 5 delivery/dispute.

---

# SLICE 1 — Rubric foundations + schema + `in_review`

Produces the durable schema and seeded rubric reference everything else builds on.

## Task 1: Rubric constants module

**Files:**
- Create: `app/modules/attestation/rubrics.py`
- Test: `tests/unit/modules/test_attestation_rubrics.py`

**Interfaces:**
- Produces:
  - `RUBRICS: dict[str, list[RubricDimension]]` keyed by review_type (`"quality"|"compliance"|"expert"|"provenance"`).
  - `RubricDimension` = `dataclass(key: str, label: str, weight: Decimal, display_order: int)`.
  - `METHODOLOGY: dict[str, str]` keyed by review_type.
  - `RUBRIC_VERSION: int = 1`.
  - `weighted_overall(scores: dict[str, int], review_type: str) -> Decimal` — returns `Decimal` quantized to 2 places; raises `ValueError` if any dimension key for the type is missing or a score is outside 1–5.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the seeded attestation review rubrics."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.attestation import rubrics


def test_every_review_type_weights_sum_to_one() -> None:
    """Each review_type's dimension weights must sum to exactly 1.000."""
    for review_type, dims in rubrics.RUBRICS.items():
        total = sum((d.weight for d in dims), Decimal("0"))
        assert total == Decimal("1.000"), f"{review_type} sums to {total}"


def test_quality_has_eight_dimensions() -> None:
    """Quality rubric mirrors workflow §4.2's eight-dimension set."""
    keys = [d.key for d in rubrics.RUBRICS["quality"]]
    assert keys == [
        "completeness",
        "implementability",
        "accuracy",
        "clarity",
        "version_currency",
        "appropriate_scope",
        "risk_flags",
        "recommended_use_cases",
    ]


def test_weighted_overall_all_fives_is_five() -> None:
    """A perfect score across every dimension yields 5.00."""
    scores = {d.key: 5 for d in rubrics.RUBRICS["provenance"]}
    assert rubrics.weighted_overall(scores, "provenance") == Decimal("5.00")


def test_weighted_overall_rejects_missing_dimension() -> None:
    """Missing a dimension score is a programming error, not a silent 0."""
    with pytest.raises(ValueError):
        rubrics.weighted_overall({"authorship_verification": 5}, "provenance")


def test_weighted_overall_rejects_out_of_range() -> None:
    """Scores outside 1–5 raise."""
    scores = {d.key: 5 for d in rubrics.RUBRICS["quality"]}
    scores["clarity"] = 6
    with pytest.raises(ValueError):
        rubrics.weighted_overall(scores, "quality")


def test_every_type_has_methodology() -> None:
    """Every review_type carries canned §4.6(c) methodology text."""
    for review_type in rubrics.RUBRICS:
        assert rubrics.METHODOLOGY[review_type].strip()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/modules/test_attestation_rubrics.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.attestation.rubrics`.

- [ ] **Step 3: Write minimal implementation**

```python
"""Seeded review rubrics for the Attestation Review Workspace (Module 4).

Rubrics are durable compliance artifacts: a published report must reproduce the
exact rubric version it used. These constants are the source seeded into the
database by migration 2026_07_01_0048 and referenced by the quality gate and
report renderer. Change = new version + new migration, never an in-place edit.

Maps to: workflow-doc §4.2, §4.6(c). Design spec §3.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

RUBRIC_VERSION: int = 1


@dataclass(frozen=True)
class RubricDimension:
    """One scored dimension within a review_type rubric."""

    key: str
    label: str
    weight: Decimal
    display_order: int


def _dims(rows: list[tuple[str, str, str]]) -> list[RubricDimension]:
    """Build ordered RubricDimension rows from (key, label, weight) tuples."""
    return [
        RubricDimension(key=k, label=label, weight=Decimal(w), display_order=i)
        for i, (k, label, w) in enumerate(rows)
    ]


RUBRICS: dict[str, list[RubricDimension]] = {
    "quality": _dims(
        [
            ("completeness", "Completeness", "0.18"),
            ("implementability", "Implementability", "0.18"),
            ("accuracy", "Accuracy", "0.18"),
            ("clarity", "Clarity", "0.12"),
            ("version_currency", "Version Currency", "0.10"),
            ("appropriate_scope", "Appropriate Scope", "0.10"),
            ("risk_flags", "Risk Flags", "0.08"),
            ("recommended_use_cases", "Recommended Use Cases", "0.06"),
        ]
    ),
    "compliance": _dims(
        [
            ("regulatory_alignment", "Regulatory Alignment", "0.25"),
            ("jurisdictional_coverage", "Jurisdictional Coverage", "0.20"),
            ("control_adequacy", "Control Adequacy", "0.20"),
            ("evidence_traceability", "Evidence Traceability", "0.15"),
            ("gap_identification", "Gap Identification", "0.12"),
            ("update_currency", "Update Currency", "0.08"),
        ]
    ),
    "expert": _dims(
        [
            ("technical_soundness", "Technical Soundness", "0.25"),
            ("methodological_rigor", "Methodological Rigor", "0.20"),
            ("domain_accuracy", "Domain Accuracy", "0.20"),
            ("practical_applicability", "Practical Applicability", "0.15"),
            ("innovation_value", "Innovation Value", "0.10"),
            ("limitations_disclosure", "Limitations Disclosure", "0.10"),
        ]
    ),
    "provenance": _dims(
        [
            ("authorship_verification", "Authorship Verification", "0.30"),
            ("source_integrity", "Source Integrity", "0.25"),
            ("originality", "Originality", "0.20"),
            ("chain_of_custody", "Chain of Custody", "0.15"),
            ("attribution_completeness", "Attribution Completeness", "0.10"),
        ]
    ),
}

METHODOLOGY: dict[str, str] = {
    "quality": (
        "This review assessed the framework against the Auracles Quality rubric: "
        "completeness, implementability, accuracy, clarity, version currency, scope, "
        "risk flags, and recommended use. Each dimension was scored 1–5 with a "
        "written justification, weighted into an overall quality score."
    ),
    "compliance": (
        "This review assessed regulatory alignment, jurisdictional coverage, control "
        "adequacy, evidence traceability, gap identification, and update currency "
        "against the applicable regulatory baseline for the declared jurisdictions."
    ),
    "expert": (
        "This review applied domain expert judgement across technical soundness, "
        "methodological rigor, domain accuracy, practical applicability, innovation "
        "value, and disclosure of limitations."
    ),
    "provenance": (
        "This review verified authorship, source integrity, originality, chain of "
        "custody, and attribution completeness of the submitted materials."
    ),
}


def weighted_overall(scores: dict[str, int], review_type: str) -> Decimal:
    """Compute the weighted overall rubric score for a review_type.

    Args:
        scores: Mapping of dimension key to integer score (1–5). Must contain
            every dimension defined for the review_type.
        review_type: One of quality/compliance/expert/provenance.

    Returns:
        Weighted score in [1.00, 5.00], quantized to two decimal places.

    Raises:
        ValueError: If review_type is unknown, a dimension is missing, or any
            score is outside 1–5.
    """
    dims = RUBRICS.get(review_type)
    if dims is None:
        raise ValueError(f"Unknown review_type: {review_type}")
    total = Decimal("0")
    for dim in dims:
        if dim.key not in scores:
            raise ValueError(f"Missing score for dimension: {dim.key}")
        score = scores[dim.key]
        if not 1 <= score <= 5:
            raise ValueError(f"Score out of range for {dim.key}: {score}")
        total += dim.weight * Decimal(score)
    return total.quantize(Decimal("0.01"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/modules/test_attestation_rubrics.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/rubrics.py tests/unit/modules/test_attestation_rubrics.py
git commit -m "feat(attestation): seed Module 4 review rubrics and weighted-overall helper"
```

## Task 2: Models — enums, columns, and tables

**Files:**
- Modify: `app/modules/attestation/models.py`
- Test: `tests/unit/modules/test_attestation_workspace.py` (schema-presence smoke test only in this task)

**Interfaces:**
- Produces (ORM):
  - `ATTESTATION_STATUS_ENUM` gains `"in_review"`.
  - New enums: `ATTESTATION_ANNOTATION_TYPE_ENUM` (`endorsement`/`concern`/`jurisdictional_caveat`/`revision_recommended`), `ATTESTATION_CLARIFICATION_STATUS_ENUM` (`open`/`answered`/`expired`).
  - `Attestation` gains `review_started_at`, `rubric_version`, `conditions`, `submitted_late`.
  - `AttestorProfile` gains `late_submission_count`.
  - Tables: `AttestationRubricDimension`, `AttestationRubricMethodology`, `AttestationRubricScore`, `AttestationAnnotation`, `AttestationClarification`.

- [ ] **Step 1: Write the failing test**

```python
"""Unit smoke tests for Module 4 workspace ORM surface."""

from __future__ import annotations

from app.modules.attestation import models


def test_in_review_status_registered() -> None:
    """The attestation status enum includes the new in_review working state."""
    assert "in_review" in models.ATTESTATION_STATUS_ENUM.enums


def test_new_workspace_tables_declared() -> None:
    """All Module 4 child tables are mapped."""
    for table in (
        "attestation_rubric_dimensions",
        "attestation_rubric_methodology",
        "attestation_rubric_scores",
        "attestation_annotations",
        "attestation_clarifications",
    ):
        assert table in models.Base.metadata.tables


def test_attestation_gains_workspace_columns() -> None:
    """Attestation carries the workspace + late-submission columns."""
    cols = models.Attestation.__table__.columns
    for name in ("review_started_at", "rubric_version", "conditions", "submitted_late"):
        assert name in cols
    assert "late_submission_count" in models.AttestorProfile.__table__.columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/modules/test_attestation_workspace.py -v`
Expected: FAIL — `in_review` not in enum / tables missing.

- [ ] **Step 3: Write minimal implementation**

In `app/modules/attestation/models.py`:

3a. Add `"in_review"` to `ATTESTATION_STATUS_ENUM` (insert after `"accepted"`):

```python
    "accepted",
    "in_review",
    "report_submitted",
```

3b. Add the two new enum objects next to the existing attestation enums:

```python
ATTESTATION_ANNOTATION_TYPE_ENUM = ENUM(
    "endorsement",
    "concern",
    "jurisdictional_caveat",
    "revision_recommended",
    name="attestation_annotation_type_enum",
    create_type=False,
)
ATTESTATION_CLARIFICATION_STATUS_ENUM = ENUM(
    "open",
    "answered",
    "expired",
    name="attestation_clarification_status_enum",
    create_type=False,
)
```

3c. On `Attestation` (after `content_ack_version`):

```python
    review_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rubric_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_late: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
```

3d. On `AttestorProfile` (after `coi_reminder_sent_at`):

```python
    late_submission_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
```

3e. Append the five new table classes at the end of the module:

```python
class AttestationRubricDimension(Base):
    """Seeded, versioned rubric dimension for one review_type (§3.4)."""

    __tablename__ = "attestation_rubric_dimensions"
    __table_args__ = (
        UniqueConstraint(
            "review_type",
            "version",
            "key",
            name="uq_attestation_rubric_dimensions_type_version_key",
        ),
        Index(
            "idx_attestation_rubric_dimensions_type_version_order",
            "review_type",
            "version",
            "display_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    review_type: Mapped[str] = mapped_column(
        ATTESTATION_REVIEW_TYPE_ENUM, nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )


class AttestationRubricMethodology(Base):
    """Seeded canned §4.6(c) methodology text per review_type + version."""

    __tablename__ = "attestation_rubric_methodology"
    __table_args__ = (
        UniqueConstraint(
            "review_type",
            "version",
            name="uq_attestation_rubric_methodology_type_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    review_type: Mapped[str] = mapped_column(
        ATTESTATION_REVIEW_TYPE_ENUM, nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    text_body: Mapped[str] = mapped_column(Text, nullable=False)


class AttestationRubricScore(UpdatedAtMixin, CreatedAtMixin, Base):
    """One assigned-Attestor score + comment for a rubric dimension (§3.5)."""

    __tablename__ = "attestation_rubric_scores"
    __table_args__ = (
        UniqueConstraint(
            "attestation_id",
            "dimension_id",
            name="uq_attestation_rubric_scores_attestation_dimension",
        ),
        CheckConstraint(
            "score IS NULL OR (score BETWEEN 1 AND 5)",
            name="ck_attestation_rubric_scores_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    dimension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestation_rubric_dimensions.id"),
        nullable=False,
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AttestationAnnotation(UpdatedAtMixin, CreatedAtMixin, Base):
    """Free-anchor clause-level annotation feeding the report (§3.6)."""

    __tablename__ = "attestation_annotations"
    __table_args__ = (Index("idx_attestation_annotations_attestation", "attestation_id"),)

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id"),
        nullable=True,
    )
    location_label: Mapped[str] = mapped_column(Text, nullable=False)
    quoted_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotation_type: Mapped[str] = mapped_column(
        ATTESTATION_ANNOTATION_TYPE_ENUM, nullable=False
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)


class AttestationClarification(Base):
    """Attestor→Requestor clarification request with SLA-pause tracking (§3.7)."""

    __tablename__ = "attestation_clarifications"
    __table_args__ = (
        Index(
            "idx_attestation_clarifications_status_due",
            "status",
            "response_due_at",
        ),
        Index("idx_attestation_clarifications_attestation", "attestation_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    response_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        ATTESTATION_CLARIFICATION_STATUS_ENUM,
        nullable=False,
        server_default="open",
    )
```

Note: confirm `CreatedAtMixin`, `UpdatedAtMixin`, `Numeric`, `CheckConstraint`, `UniqueConstraint`, `Index`, `Integer` are already imported at the top of `models.py` (they are — see existing usage). Do not re-import.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/modules/test_attestation_workspace.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/models.py tests/unit/modules/test_attestation_workspace.py
git commit -m "feat(attestation): Module 4 workspace ORM models and enums"
```

## Task 3: Migration — schema + enum add + rubric seed

**Files:**
- Create: `migrations/versions/2026_07_01_0048_attestation_review_workspace.py`
- Test: `tests/integration/test_attestation_workspace.py` (migration round-trip + seed count)

**Interfaces:**
- Consumes: `rubrics.RUBRICS`, `rubrics.METHODOLOGY`, `rubrics.RUBRIC_VERSION` (Task 1).
- Produces: DB at head `2026_07_01_0048` with all Module 4 tables/columns and seeded rubric rows.

- [ ] **Step 1: Write the failing test**

```python
"""Integration tests for the Module 4 review-workspace migration + seed."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestationRubricMethodology,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is at alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


async def test_rubric_dimensions_seeded(migrated_database) -> None:
    """Every rubric dimension for all four review_types is seeded at version 1."""
    del migrated_database
    await engine.dispose()
    expected = sum(len(dims) for dims in rubrics.RUBRICS.values())
    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(AttestationRubricDimension)
        )
        methodology = await session.scalar(
            select(func.count()).select_from(AttestationRubricMethodology)
        )
    await engine.dispose()
    assert count == expected
    assert methodology == len(rubrics.METHODOLOGY)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_attestation_workspace.py::test_rubric_dimensions_seeded -v`
Expected: FAIL — tables/rows absent (migration not written).

- [ ] **Step 3: Write minimal implementation**

Create the migration. Model the enum-add on `2026_06_29_0041`; create tables with `op.create_table`; seed with a bulk insert built from `rubrics`.

```python
"""Add the Module 4 Review Workspace schema and seed review rubrics.

Introduces the in_review working status, rubric/annotation/clarification tables,
report workspace columns, and the attestor late-submission counter. Seeds all
four review-type rubrics (version 1) plus canned methodology text. Additive and
reversible; downgrade drops the new tables/columns but leaves the enum value in
place (Postgres cannot drop an enum value — documented no-op, per Module 1
precedent).

Maps to: design spec §3 (data model). Workflow-doc §4.2, §4.6.

Revision ID: 2026_07_01_0048
Revises: 2026_06_30_0047
Create Date: 2026-07-01
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.modules.attestation import rubrics

revision: str = "2026_07_01_0048"
down_revision: str | Sequence[str] | None = "2026_06_30_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANNOTATION_TYPE_ENUM = postgresql.ENUM(
    "endorsement",
    "concern",
    "jurisdictional_caveat",
    "revision_recommended",
    name="attestation_annotation_type_enum",
)
CLARIFICATION_STATUS_ENUM = postgresql.ENUM(
    "open",
    "answered",
    "expired",
    name="attestation_clarification_status_enum",
)
REVIEW_TYPE_ENUM = postgresql.ENUM(
    name="attestation_review_type_enum", create_type=False
)


def upgrade() -> None:
    """Create workspace schema, seed rubrics, add the in_review enum value."""
    bind = op.get_bind()

    # 1. in_review status value (ADD VALUE needs autocommit).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE attestation_status_enum "
            "ADD VALUE IF NOT EXISTS 'in_review' AFTER 'accepted'"
        )

    # 2. New enum types.
    ANNOTATION_TYPE_ENUM.create(bind, checkfirst=True)
    CLARIFICATION_STATUS_ENUM.create(bind, checkfirst=True)

    # 3. Attestation + AttestorProfile columns.
    op.add_column(
        "attestations",
        sa.Column("review_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestations", sa.Column("rubric_version", sa.Integer(), nullable=True)
    )
    op.add_column("attestations", sa.Column("conditions", sa.Text(), nullable=True))
    op.add_column(
        "attestations",
        sa.Column(
            "submitted_late",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "late_submission_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # 4. Rubric dimension table.
    op.create_table(
        "attestation_rubric_dimensions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("review_type", REVIEW_TYPE_ENUM, nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(4, 3), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint(
            "review_type",
            "version",
            "key",
            name="uq_attestation_rubric_dimensions_type_version_key",
        ),
    )
    op.create_index(
        "idx_attestation_rubric_dimensions_type_version_order",
        "attestation_rubric_dimensions",
        ["review_type", "version", "display_order"],
    )

    # 5. Methodology table.
    op.create_table(
        "attestation_rubric_methodology",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("review_type", REVIEW_TYPE_ENUM, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "review_type",
            "version",
            name="uq_attestation_rubric_methodology_type_version",
        ),
    )

    # 6. Scores table.
    op.create_table(
        "attestation_rubric_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dimension_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestation_rubric_dimensions.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "attestation_id",
            "dimension_id",
            name="uq_attestation_rubric_scores_attestation_dimension",
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score BETWEEN 1 AND 5)",
            name="ck_attestation_rubric_scores_range",
        ),
    )

    # 7. Annotations table.
    op.create_table(
        "attestation_annotations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.id"),
            nullable=True,
        ),
        sa.Column("location_label", sa.Text(), nullable=False),
        sa.Column("quoted_excerpt", sa.Text(), nullable=True),
        sa.Column("annotation_type", ANNOTATION_TYPE_ENUM, nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_attestation_annotations_attestation",
        "attestation_annotations",
        ["attestation_id"],
    )

    # 8. Clarifications table.
    op.create_table(
        "attestation_clarifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            CLARIFICATION_STATUS_ENUM,
            nullable=False,
            server_default="open",
        ),
    )
    op.create_index(
        "idx_attestation_clarifications_status_due",
        "attestation_clarifications",
        ["status", "response_due_at"],
    )
    op.create_index(
        "idx_attestation_clarifications_attestation",
        "attestation_clarifications",
        ["attestation_id"],
    )

    # 9. Seed rubric dimensions + methodology from the constants module.
    dimension_rows = [
        {
            "id": uuid.uuid4(),
            "review_type": review_type,
            "key": dim.key,
            "label": dim.label,
            "weight": Decimal(dim.weight),
            "display_order": dim.display_order,
            "version": rubrics.RUBRIC_VERSION,
        }
        for review_type, dims in rubrics.RUBRICS.items()
        for dim in dims
    ]
    op.bulk_insert(
        sa.table(
            "attestation_rubric_dimensions",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("review_type", sa.Text()),
            sa.column("key", sa.Text()),
            sa.column("label", sa.Text()),
            sa.column("weight", sa.Numeric(4, 3)),
            sa.column("display_order", sa.Integer()),
            sa.column("version", sa.Integer()),
        ),
        dimension_rows,
    )
    methodology_rows = [
        {
            "id": uuid.uuid4(),
            "review_type": review_type,
            "version": rubrics.RUBRIC_VERSION,
            "text_body": text_body,
        }
        for review_type, text_body in rubrics.METHODOLOGY.items()
    ]
    op.bulk_insert(
        sa.table(
            "attestation_rubric_methodology",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("review_type", sa.Text()),
            sa.column("version", sa.Integer()),
            sa.column("text_body", sa.Text()),
        ),
        methodology_rows,
    )


def downgrade() -> None:
    """Drop workspace tables/columns. Enum value in_review is left in place."""
    op.drop_index(
        "idx_attestation_clarifications_attestation",
        table_name="attestation_clarifications",
    )
    op.drop_index(
        "idx_attestation_clarifications_status_due",
        table_name="attestation_clarifications",
    )
    op.drop_table("attestation_clarifications")
    op.drop_index(
        "idx_attestation_annotations_attestation",
        table_name="attestation_annotations",
    )
    op.drop_table("attestation_annotations")
    op.drop_table("attestation_rubric_scores")
    op.drop_table("attestation_rubric_methodology")
    op.drop_index(
        "idx_attestation_rubric_dimensions_type_version_order",
        table_name="attestation_rubric_dimensions",
    )
    op.drop_table("attestation_rubric_dimensions")
    op.drop_column("attestor_profiles", "late_submission_count")
    op.drop_column("attestations", "submitted_late")
    op.drop_column("attestations", "conditions")
    op.drop_column("attestations", "rubric_version")
    op.drop_column("attestations", "review_started_at")
    bind = op.get_bind()
    ANNOTATION_TYPE_ENUM.drop(bind, checkfirst=True)
    CLARIFICATION_STATUS_ENUM.drop(bind, checkfirst=True)
```

- [ ] **Step 4: Run test + round-trip**

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run pytest tests/integration/test_attestation_workspace.py::test_rubric_dimensions_seeded -v
```
Expected: all succeed; test PASS. (Downgrade must not error on the retained enum value.)

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/2026_07_01_0048_attestation_review_workspace.py tests/integration/test_attestation_workspace.py
git commit -m "feat(attestation): Module 4 workspace migration and rubric seed"
```

## Task 4: Slice-1 gate

- [ ] **Step 1: Run full slice + repo gates**

```bash
uv run pytest tests/unit/modules/test_attestation_rubrics.py tests/unit/modules/test_attestation_workspace.py tests/integration/test_attestation_workspace.py -v
uv run ruff check .
uv run mypy app
```
Expected: all green.

- [ ] **Step 2: Nothing to commit if clean.** Slice 1 done — hand to reviewer.

---

# SLICE 2 — Workspace CRUD (start-review, rubric scoring, annotations)

## Task 5: Shared 404 assigned-Attestor loader + `start_review`

**Files:**
- Create: `app/modules/attestation/workspace_service.py`
- Test: `tests/integration/test_attestation_workspace.py` (append)

**Interfaces:**
- Produces:
  - `async def load_workspace_attestation(db, *, attestation_id: UUID, attestor_id: UUID, allowed_statuses: set[str]) -> Attestation` — 404 if not found **or** attestor mismatch (hide existence); 409 if status not allowed. Uses `with_for_update()`.
  - `async def start_review(db, *, attestor: User, attestation_id: UUID) -> Attestation` — `accepted → in_review`, stamps `review_started_at`, audit `attestation_review_started`; idempotent when already `in_review`.

**Design note:** the existing `report._load_assigned_attestation_for_update` returns **403** on mismatch and is used by the already-shipped report/evidence path — leave it untouched. Module 4 endpoints use the new **404** loader here.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_attestation_workspace.py` (reuse the `migrated_database` fixture; add helpers to create a user, attestor profile, and an `accepted` attestation assigned to that attestor — mirror the factory helpers in `tests/integration/test_attestation_offers.py`).

```python
async def test_start_review_transitions_accepted_to_in_review(db_session) -> None:
    """The assigned Attestor opening the workspace moves accepted → in_review."""
    attestor, attestation = await _accepted_attestation(db_session)
    result = await workspace_service.start_review(
        db_session, attestor=attestor, attestation_id=attestation.id
    )
    assert result.status == "in_review"
    assert result.review_started_at is not None


async def test_start_review_is_idempotent(db_session) -> None:
    """Calling start_review twice leaves a single in_review state, no error."""
    attestor, attestation = await _accepted_attestation(db_session)
    await workspace_service.start_review(
        db_session, attestor=attestor, attestation_id=attestation.id
    )
    again = await workspace_service.start_review(
        db_session, attestor=attestor, attestation_id=attestation.id
    )
    assert again.status == "in_review"


async def test_start_review_404_for_non_assigned(db_session) -> None:
    """A non-assigned attestor cannot see the attestation exists (404)."""
    _assigned, attestation = await _accepted_attestation(db_session)
    intruder = await _make_attestor(db_session, "intruder")
    with pytest.raises(HTTPException) as exc:
        await workspace_service.start_review(
            db_session, attestor=intruder, attestation_id=attestation.id
        )
    assert exc.value.status_code == 404
```

(Provide `_accepted_attestation`, `_make_attestor`, and a `db_session` fixture in the test file — copy the session/clean-state fixture shape from `tests/integration/test_attestation_offers.py`, adding `AttestationRubricScore`, `AttestationAnnotation`, `AttestationClarification` to the reset delete list.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_attestation_workspace.py -k start_review -v`
Expected: FAIL — `workspace_service` missing.

- [ ] **Step 3: Write minimal implementation**

```python
"""Attestation Review Workspace service (Module 4).

Assigned-Attestor working environment: opening the workspace (start_review),
rubric scoring, and clause-level annotations. Every entry point is restricted to
the assigned Attestor and hides existence (404) from anyone else.

Maps to: workflow-doc §4.1–4.3. Design spec §4.1–4.3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationRubricDimension,
    AttestationRubricScore,
)
from app.modules.auth.models import User


async def load_workspace_attestation(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    attestor_id: UUID,
    allowed_statuses: set[str],
    lock: bool = True,
) -> Attestation:
    """Load an Attestation assigned to one Attestor, hiding existence on mismatch.

    Args:
        db: Async session.
        attestation_id: Attestation to load.
        attestor_id: The requesting Attestor; must be the assignee.
        allowed_statuses: States in which the operation is permitted.
        lock: Whether to take a row lock (SELECT ... FOR UPDATE).

    Returns:
        The Attestation row.

    Raises:
        HTTPException(404): Not found, or the requester is not the assignee.
        HTTPException(409): Found and assigned but not in an allowed status.
    """
    stmt = select(Attestation).where(Attestation.id == attestation_id)
    if lock:
        stmt = stmt.with_for_update()
    attestation = await db.scalar(stmt)
    if attestation is None or attestation.attestor_id != attestor_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if attestation.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation is not in a workspace-editable state.",
        )
    return attestation


async def start_review(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
) -> Attestation:
    """Open the review workspace, moving accepted → in_review (idempotent)."""
    if db.in_transaction():
        await db.rollback()
    now = datetime.now(UTC)
    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor.id,
            allowed_statuses={"accepted", "in_review"},
        )
        if attestation.status == "accepted":
            attestation.status = "in_review"
            attestation.review_started_at = now
            await write_audit(
                db=db,
                actor_id=attestor.id,
                action="attestation_review_started",
                target_type="attestation",
                target_id=attestation.id,
                metadata={"review_type": attestation.review_type},
            )
    await db.refresh(attestation)
    return attestation
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_attestation_workspace.py -k start_review -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/workspace_service.py tests/integration/test_attestation_workspace.py
git commit -m "feat(attestation): start-review workspace transition with 404 hiding"
```

## Task 6: Rubric-score upsert

**Files:**
- Modify: `app/modules/attestation/workspace_service.py`
- Test: `tests/integration/test_attestation_workspace.py` (append)

**Interfaces:**
- Produces: `async def upsert_rubric_score(db, *, attestor: User, attestation_id: UUID, dimension_key: str, score: int | None, comment: str | None) -> AttestationRubricScore`. Validates `dimension_key` belongs to the attestation's `review_type` at the current `RUBRIC_VERSION`; 422 if not. Partial (score or comment) allowed. Only in `in_review`.

- [ ] **Step 1: Write the failing test**

```python
async def test_upsert_rubric_score_creates_then_updates(db_session) -> None:
    """Scoring a dimension upserts one row per (attestation, dimension)."""
    attestor, attestation = await _in_review_attestation(db_session)  # quality type
    first = await workspace_service.upsert_rubric_score(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        dimension_key="completeness",
        score=4,
        comment="Thorough.",
    )
    assert first.score == 4
    second = await workspace_service.upsert_rubric_score(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        dimension_key="completeness",
        score=5,
        comment="Revised up.",
    )
    assert second.id == first.id
    assert second.score == 5


async def test_upsert_rubric_score_rejects_foreign_dimension(db_session) -> None:
    """A dimension key not in the attestation's review_type is a 422."""
    attestor, attestation = await _in_review_attestation(db_session)  # quality
    with pytest.raises(HTTPException) as exc:
        await workspace_service.upsert_rubric_score(
            db_session,
            attestor=attestor,
            attestation_id=attestation.id,
            dimension_key="chain_of_custody",  # provenance-only
            score=3,
            comment="x",
        )
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_attestation_workspace.py -k rubric_score -v`
Expected: FAIL — function missing.

- [ ] **Step 3: Write minimal implementation**

Append to `workspace_service.py`:

```python
async def upsert_rubric_score(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    dimension_key: str,
    score: int | None,
    comment: str | None,
) -> AttestationRubricScore:
    """Create or update the Attestor's score for one rubric dimension."""
    if score is not None and not 1 <= score <= 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Score must be between 1 and 5.",
        )
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor.id,
            allowed_statuses={"in_review"},
        )
        dimension = await db.scalar(
            select(AttestationRubricDimension).where(
                AttestationRubricDimension.review_type == attestation.review_type,
                AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                AttestationRubricDimension.key == dimension_key,
            )
        )
        if dimension is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unknown rubric dimension for this review type.",
            )
        row = await db.scalar(
            select(AttestationRubricScore).where(
                AttestationRubricScore.attestation_id == attestation.id,
                AttestationRubricScore.dimension_id == dimension.id,
            )
        )
        if row is None:
            row = AttestationRubricScore(
                attestation_id=attestation.id,
                dimension_id=dimension.id,
                score=score,
                comment=comment,
            )
            db.add(row)
        else:
            row.score = score
            row.comment = comment
        await db.flush()
    await db.refresh(row)
    return row
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_attestation_workspace.py -k rubric_score -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/workspace_service.py tests/integration/test_attestation_workspace.py
git commit -m "feat(attestation): rubric score upsert with dimension validation"
```

## Task 7: Annotation CRUD

**Files:**
- Modify: `app/modules/attestation/workspace_service.py`
- Test: `tests/integration/test_attestation_workspace.py` (append)

**Interfaces:**
- Produces:
  - `async def create_annotation(db, *, attestor, attestation_id, artifact_id: UUID | None, location_label: str, quoted_excerpt: str | None, annotation_type: str, comment: str) -> AttestationAnnotation`
  - `async def update_annotation(db, *, attestor, attestation_id, annotation_id, **fields) -> AttestationAnnotation`
  - `async def delete_annotation(db, *, attestor, attestation_id, annotation_id) -> None`
  All require `in_review` + assignee (404 otherwise). `annotation_type` ∈ the four enum values.

- [ ] **Step 1: Write the failing test**

```python
async def test_create_and_delete_annotation(db_session) -> None:
    """The Attestor can attach and remove a free-anchor annotation."""
    attestor, attestation = await _in_review_attestation(db_session)
    ann = await workspace_service.create_annotation(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        artifact_id=None,
        location_label="Section 3.2",
        quoted_excerpt="the clause text",
        annotation_type="concern",
        comment="Ambiguous scope.",
    )
    assert ann.annotation_type == "concern"
    await workspace_service.delete_annotation(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        annotation_id=ann.id,
    )
    remaining = await workspace_service.list_annotations(
        db_session, attestor=attestor, attestation_id=attestation.id
    )
    assert remaining == []


async def test_create_annotation_rejects_bad_type(db_session) -> None:
    """An unknown annotation_type is a 422."""
    attestor, attestation = await _in_review_attestation(db_session)
    with pytest.raises(HTTPException) as exc:
        await workspace_service.create_annotation(
            db_session,
            attestor=attestor,
            attestation_id=attestation.id,
            artifact_id=None,
            location_label="x",
            quoted_excerpt=None,
            annotation_type="applause",
            comment="c",
        )
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_attestation_workspace.py -k annotation -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Append to `workspace_service.py` (add the module constant + functions):

```python
ANNOTATION_TYPES = {
    "endorsement",
    "concern",
    "jurisdictional_caveat",
    "revision_recommended",
}


async def list_annotations(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
) -> list[AttestationAnnotation]:
    """Return the Attestor's annotations for an attestation (read-only)."""
    await load_workspace_attestation(
        db,
        attestation_id=attestation_id,
        attestor_id=attestor.id,
        allowed_statuses={"in_review", "report_submitted"},
        lock=False,
    )
    rows = await db.scalars(
        select(AttestationAnnotation)
        .where(AttestationAnnotation.attestation_id == attestation_id)
        .order_by(AttestationAnnotation.created_at)
    )
    return list(rows)


async def create_annotation(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    artifact_id: UUID | None,
    location_label: str,
    quoted_excerpt: str | None,
    annotation_type: str,
    comment: str,
) -> AttestationAnnotation:
    """Attach one free-anchor annotation to the attestation under review."""
    if annotation_type not in ANNOTATION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown annotation type.",
        )
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor.id,
            allowed_statuses={"in_review"},
        )
        annotation = AttestationAnnotation(
            attestation_id=attestation.id,
            artifact_id=artifact_id,
            location_label=location_label,
            quoted_excerpt=quoted_excerpt,
            annotation_type=annotation_type,
            comment=comment,
        )
        db.add(annotation)
        await db.flush()
    await db.refresh(annotation)
    return annotation


async def _load_owned_annotation(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    annotation_id: UUID,
) -> AttestationAnnotation:
    """Load one annotation, enforcing assignee + in_review, else 404."""
    await load_workspace_attestation(
        db,
        attestation_id=attestation_id,
        attestor_id=attestor.id,
        allowed_statuses={"in_review"},
    )
    annotation = await db.scalar(
        select(AttestationAnnotation).where(
            AttestationAnnotation.id == annotation_id,
            AttestationAnnotation.attestation_id == attestation_id,
        )
    )
    if annotation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found.",
        )
    return annotation


async def update_annotation(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    annotation_id: UUID,
    location_label: str,
    quoted_excerpt: str | None,
    annotation_type: str,
    comment: str,
) -> AttestationAnnotation:
    """Replace the editable fields of one annotation."""
    if annotation_type not in ANNOTATION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown annotation type.",
        )
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        annotation = await _load_owned_annotation(
            db,
            attestor=attestor,
            attestation_id=attestation_id,
            annotation_id=annotation_id,
        )
        annotation.location_label = location_label
        annotation.quoted_excerpt = quoted_excerpt
        annotation.annotation_type = annotation_type
        annotation.comment = comment
        await db.flush()
    await db.refresh(annotation)
    return annotation


async def delete_annotation(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    annotation_id: UUID,
) -> None:
    """Remove one annotation owned by the assigned Attestor."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        annotation = await _load_owned_annotation(
            db,
            attestor=attestor,
            attestation_id=attestation_id,
            annotation_id=annotation_id,
        )
        await db.delete(annotation)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_attestation_workspace.py -k annotation -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/workspace_service.py tests/integration/test_attestation_workspace.py
git commit -m "feat(attestation): clause-level annotation CRUD"
```

## Task 8: Schemas + router wiring + OpenAPI

**Files:**
- Modify: `app/modules/attestation/schemas.py`, `app/modules/attestation/router.py`, `contracts/openapi.yaml`
- Test: `tests/integration/test_attestation_workspace.py` (append endpoint tests)

**Interfaces:**
- Produces Pydantic: `RubricScoreUpsertRequest(score: int | None, comment: str | None)`, `AnnotationCreateRequest`, `AnnotationUpdateRequest`, `RubricScoreResponse`, `AnnotationResponse`, `WorkspaceResponse` (attestation status + review_started_at + rubric rows + annotations). Response models use `model_config = ConfigDict(from_attributes=True)`.
- Endpoints (all `Depends(require_approved_attestor)` → `ApprovedAttestorUser`):
  - `POST /v1/attestations/{attestation_id}/start-review`
  - `PUT  /v1/attestations/{attestation_id}/rubric/{dimension_key}`
  - `GET  /v1/attestations/{attestation_id}/annotations`
  - `POST /v1/attestations/{attestation_id}/annotations`
  - `PATCH /v1/attestations/{attestation_id}/annotations/{annotation_id}`
  - `DELETE /v1/attestations/{attestation_id}/annotations/{annotation_id}`

- [ ] **Step 1: Write the failing test**

Add endpoint-level tests hitting the app via `AsyncClient` (mirror auth/setup helpers in `tests/integration/test_attestation_offers.py` or the existing attestation endpoint tests). Cover: start-review 200 + status flips; PUT rubric 200; non-assigned attestor → 404; unauthenticated → 401.

```python
async def test_start_review_endpoint_flips_status(auth_attestor_client, in_review_seed) -> None:
    """POST /start-review returns 200 and reports in_review."""
    attestation_id = in_review_seed
    resp = await auth_attestor_client.post(
        f"/v1/attestations/{attestation_id}/start-review"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_review"
```

(Define `auth_attestor_client` + `in_review_seed` fixtures following the existing attestation integration-test auth pattern — issue a token for the assigned attestor.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_attestation_workspace.py -k endpoint -v`
Expected: FAIL — endpoints 404 (not registered).

- [ ] **Step 3: Write minimal implementation**

3a. Add schemas to `schemas.py` (follow existing `AttestationReportSubmitRequest` style; import `ConfigDict`, `Field`, `Literal`, `UUID`, `datetime` as already used):

```python
class RubricScoreUpsertRequest(BaseModel):
    """Draft score + comment for one rubric dimension."""

    score: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=5000)


class RubricScoreResponse(BaseModel):
    """One persisted rubric score row."""

    model_config = ConfigDict(from_attributes=True)

    dimension_id: UUID
    score: int | None
    comment: str | None


class AnnotationCreateRequest(BaseModel):
    """Free-anchor annotation input."""

    artifact_id: UUID | None = None
    location_label: str = Field(min_length=1, max_length=500)
    quoted_excerpt: str | None = Field(default=None, max_length=5000)
    annotation_type: Literal[
        "endorsement", "concern", "jurisdictional_caveat", "revision_recommended"
    ]
    comment: str = Field(min_length=1, max_length=5000)


class AnnotationUpdateRequest(AnnotationCreateRequest):
    """Same editable fields as create (full replace)."""


class AnnotationResponse(BaseModel):
    """One persisted annotation row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    artifact_id: UUID | None
    location_label: str
    quoted_excerpt: str | None
    annotation_type: str
    comment: str
```

3b. Add endpoints to `router.py`. Thin handlers → service. Example (repeat the pattern for each):

```python
@router.post(
    "/attestations/{attestation_id}/start-review",
    response_model=AttestationRequestResponse,
    summary="Open the review workspace",
)
async def start_attestation_review(
    attestation_id: UUID,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Move an accepted assignment into the in_review working state."""
    attestation = await workspace_service.start_review(
        db=db, attestor=attestor, attestation_id=attestation_id
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.put(
    "/attestations/{attestation_id}/rubric/{dimension_key}",
    response_model=RubricScoreResponse,
    summary="Score one rubric dimension",
)
async def upsert_attestation_rubric_score(
    attestation_id: UUID,
    dimension_key: str,
    payload: RubricScoreUpsertRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> RubricScoreResponse:
    """Create or update the Attestor's score+comment for a rubric dimension."""
    row = await workspace_service.upsert_rubric_score(
        db=db,
        attestor=attestor,
        attestation_id=attestation_id,
        dimension_key=dimension_key,
        score=payload.score,
        comment=payload.comment,
    )
    return RubricScoreResponse.model_validate(row)
```

Add `GET`/`POST`/`PATCH`/`DELETE` annotation endpoints similarly, calling `workspace_service.list_annotations` / `create_annotation` / `update_annotation` / `delete_annotation`, returning `AnnotationResponse` (or `list[AnnotationResponse]`; DELETE returns `status_code=204`). Import `workspace_service` and the new schemas at the top of `router.py`.

3c. Update `contracts/openapi.yaml` — add the six paths with request/response schemas mirroring the Pydantic models above (the frontend client regenerates from this).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_attestation_workspace.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/schemas.py app/modules/attestation/router.py contracts/openapi.yaml tests/integration/test_attestation_workspace.py
git commit -m "feat(attestation): workspace endpoints for start-review, rubric, annotations"
```

## Task 9: Slice-2 gate

- [ ] **Step 1: Run gates**

```bash
uv run pytest tests/integration/test_attestation_workspace.py tests/unit/modules/test_attestation_workspace.py -v
uv run ruff check .
uv run mypy app
```
Expected: green. Slice 2 done.

---

# SLICE 3 — Clarifications + SLA pause + revoke-beat widening

## Task 10: Clarification send with deadline extension + max-2

**Files:**
- Create: `app/modules/attestation/clarification_service.py`
- Test: `tests/unit/modules/test_attestation_clarifications.py`

**Interfaces:**
- Produces:
  - `CLARIFICATION_RESPONSE_HOURS_DEFAULT = 48`
  - `async def send_clarification(db, *, attestor: User, attestation_id: UUID, question: str, now: datetime | None = None) -> AttestationClarification` — 422 if 2 exist or an `open` one exists; sets `response_due_at = now + hours`, **extends** `completion_due_at += hours`, audit `attestation_clarification_sent`.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for attestation clarification SLA-pause math."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.modules.attestation import clarification_service

pytestmark = pytest.mark.asyncio


async def test_send_extends_completion_deadline(db_session) -> None:
    """Sending a clarification pushes completion_due_at out by the 48h window."""
    attestor, attestation = await _in_review_attestation(db_session)
    before = attestation.completion_due_at
    now = datetime.now(UTC)
    clar = await clarification_service.send_clarification(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        question="Which framework version is in scope?",
        now=now,
    )
    refreshed = await db_session.get(type(attestation), attestation.id)
    assert clar.response_due_at == now + timedelta(hours=48)
    assert refreshed.completion_due_at == before + timedelta(hours=48)


async def test_third_clarification_rejected(db_session) -> None:
    """No more than two clarifications per assignment."""
    attestor, attestation = await _in_review_attestation(db_session)
    for i in range(2):
        clar = await clarification_service.send_clarification(
            db_session, attestor=attestor, attestation_id=attestation.id,
            question=f"q{i}",
        )
        # answer it so the next send isn't blocked by the open-guard
        await _force_answer(db_session, clar.id)
    with pytest.raises(HTTPException) as exc:
        await clarification_service.send_clarification(
            db_session, attestor=attestor, attestation_id=attestation.id, question="q3"
        )
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/modules/test_attestation_clarifications.py -k send -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
"""Attestation clarification requests with SLA-pause accounting (Module 4).

The Attestor may ask the Requestor up to two clarifying questions. Each open
question extends the completion SLA by the full response window up front; an
early answer returns the unused remainder. The deadline is only ever pushed
out before a response arrives, so the overdue-revocation beat never fires
mid-clarification.

Maps to: workflow-doc §4.4. Design spec §4.4.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import Attestation, AttestationClarification
from app.modules.attestation.workspace_service import load_workspace_attestation
from app.modules.auth.models import User
from app.modules.financials.models import PlatformConfig

CLARIFICATION_RESPONSE_HOURS_DEFAULT = 48
MAX_CLARIFICATIONS = 2


async def _response_hours(db: AsyncSession) -> int:
    """Read the configured clarification response window in hours."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "attestation_clarification_response_hours"
        )
    )
    if configured is None:
        return CLARIFICATION_RESPONSE_HOURS_DEFAULT
    try:
        parsed = int(configured)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="attestation_clarification_response_hours is invalid.",
        ) from exc
    if parsed < 1:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="attestation_clarification_response_hours is invalid.",
        )
    return parsed


async def send_clarification(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    question: str,
    now: datetime | None = None,
) -> AttestationClarification:
    """Send one Attestor→Requestor clarification, extending the SLA deadline."""
    current_time = now or datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor.id,
            allowed_statuses={"in_review"},
        )
        total = await db.scalar(
            select(func.count()).select_from(AttestationClarification).where(
                AttestationClarification.attestation_id == attestation.id
            )
        )
        if total >= MAX_CLARIFICATIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Clarification limit reached for this assignment.",
            )
        open_exists = await db.scalar(
            select(func.count()).select_from(AttestationClarification).where(
                AttestationClarification.attestation_id == attestation.id,
                AttestationClarification.status == "open",
            )
        )
        if open_exists:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="An open clarification is already awaiting a response.",
            )
        hours = await _response_hours(db)
        due = current_time + timedelta(hours=hours)
        clarification = AttestationClarification(
            attestation_id=attestation.id,
            question=question,
            sent_at=current_time,
            response_due_at=due,
            status="open",
        )
        db.add(clarification)
        if attestation.completion_due_at is not None:
            attestation.completion_due_at = attestation.completion_due_at + timedelta(
                hours=hours
            )
        await write_audit(
            db=db,
            actor_id=attestor.id,
            action="attestation_clarification_sent",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"response_hours": hours},
        )
        await db.flush()
    await db.refresh(clarification)
    attestation_notifications.notify_clarification_requested(
        attestation, requestor_id=attestation.requestor_id
    )
    return clarification
```

Add `notify_clarification_requested` / `notify_clarification_answered` to `notifications.py` in this step (mirror the existing `_dispatch` helpers; user-targeted, no PII):

```python
def notify_clarification_requested(attestation: Attestation, *, requestor_id: UUID) -> None:
    """Notify the Requestor that the Attestor asked a clarifying question."""
    _dispatch(
        user_id=requestor_id,
        notification_type="attestation_clarification_requested",
        title="Clarification requested",
        body="The assigned Attestor asked a question about your attestation request.",
        attestation=attestation,
        dedupe_suffix="clarification-requested",
    )


def notify_clarification_answered(attestation: Attestation, *, attestor_id: UUID) -> None:
    """Notify the Attestor that the Requestor answered a clarification."""
    _dispatch(
        user_id=attestor_id,
        notification_type="attestation_clarification_answered",
        title="Clarification answered",
        body="The Requestor answered your clarifying question.",
        attestation=attestation,
        dedupe_suffix="clarification-answered",
    )
```

(`_dispatch`'s `dedupe_suffix` becomes non-unique if two clarifications occur — acceptable; the workspace shows the live rows. If stricter dedupe is wanted, append the clarification id.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/modules/test_attestation_clarifications.py -k send -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/clarification_service.py app/modules/attestation/notifications.py tests/unit/modules/test_attestation_clarifications.py
git commit -m "feat(attestation): clarification send with SLA deadline extension"
```

## Task 11: Clarification respond (Requestor) with remainder trim

**Files:**
- Modify: `app/modules/attestation/clarification_service.py`
- Test: `tests/unit/modules/test_attestation_clarifications.py` (append)

**Interfaces:**
- Produces: `async def respond_to_clarification(db, *, requestor: User, attestation_id: UUID, clarification_id: UUID, response: str, now: datetime | None = None) -> AttestationClarification`. Requestor-only (404 if not the requestor or not found). Sets `response`, `responded_at`, `status="answered"`; trims `completion_due_at -= (response_due_at - responded_at)` (return unused remainder). 409 if already answered/expired.

- [ ] **Step 1: Write the failing test**

```python
async def test_respond_trims_unused_remainder(db_session) -> None:
    """Answering early returns the unused pause remainder to the deadline."""
    attestor, attestation = await _in_review_attestation(db_session)
    now = datetime.now(UTC)
    clar = await clarification_service.send_clarification(
        db_session, attestor=attestor, attestation_id=attestation.id,
        question="q", now=now,
    )
    extended = (await db_session.get(type(attestation), attestation.id)).completion_due_at
    responded = now + timedelta(hours=10)  # 38h unused
    requestor = await _requestor_of(db_session, attestation)
    await clarification_service.respond_to_clarification(
        db_session, requestor=requestor, attestation_id=attestation.id,
        clarification_id=clar.id, response="v2", now=responded,
    )
    refreshed = await db_session.get(type(attestation), attestation.id)
    assert refreshed.completion_due_at == extended - timedelta(hours=38)


async def test_only_requestor_can_respond(db_session) -> None:
    """A non-requestor answering is hidden (404)."""
    attestor, attestation = await _in_review_attestation(db_session)
    clar = await clarification_service.send_clarification(
        db_session, attestor=attestor, attestation_id=attestation.id, question="q",
    )
    with pytest.raises(HTTPException) as exc:
        await clarification_service.respond_to_clarification(
            db_session, requestor=attestor, attestation_id=attestation.id,
            clarification_id=clar.id, response="x",
        )
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/modules/test_attestation_clarifications.py -k respond -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Append to `clarification_service.py`:

```python
async def respond_to_clarification(
    db: AsyncSession,
    *,
    requestor: User,
    attestation_id: UUID,
    clarification_id: UUID,
    response: str,
    now: datetime | None = None,
) -> AttestationClarification:
    """Record the Requestor's answer and return the unused SLA remainder."""
    current_time = now or datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await db.scalar(
            select(Attestation).where(Attestation.id == attestation_id).with_for_update()
        )
        # Requestor-only, hide existence otherwise.
        if attestation is None or attestation.requestor_id != requestor.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        clarification = await db.scalar(
            select(AttestationClarification).where(
                AttestationClarification.id == clarification_id,
                AttestationClarification.attestation_id == attestation_id,
            ).with_for_update()
        )
        if clarification is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clarification not found.",
            )
        if clarification.status != "open":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Clarification is no longer open.",
            )
        clarification.response = response
        clarification.responded_at = current_time
        clarification.status = "answered"
        remainder = clarification.response_due_at - current_time
        if remainder.total_seconds() > 0 and attestation.completion_due_at is not None:
            attestation.completion_due_at = attestation.completion_due_at - remainder
        await write_audit(
            db=db,
            actor_id=requestor.id,
            action="attestation_clarification_answered",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"clarification_id": str(clarification.id)},
        )
        await db.flush()
    await db.refresh(clarification)
    if attestation.attestor_id is not None:
        attestation_notifications.notify_clarification_answered(
            attestation, attestor_id=attestation.attestor_id
        )
    return clarification
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/modules/test_attestation_clarifications.py -k respond -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/clarification_service.py tests/unit/modules/test_attestation_clarifications.py
git commit -m "feat(attestation): clarification response with SLA remainder trim"
```

## Task 12: Expiry sweep + widen revoke-beat + beat wiring

**Files:**
- Modify: `app/modules/attestation/clarification_service.py`, `app/modules/attestation/matching_service.py`, `app/workers/tasks/attestation_beat.py`, `app/workers/beat_schedule.py`
- Test: `tests/unit/modules/test_attestation_clarifications.py` (append), `tests/unit/workers/test_attestation_clarification_expiry.py`, `tests/unit/workers/test_attestation_beat_tasks.py` (append registration assertion)

**Interfaces:**
- Produces:
  - `async def expire_clarifications(db, *, now: datetime | None = None) -> int` — `open` past `response_due_at` → `status="expired"`, `responded_at=now`; deadline already carries the full window so no adjustment; notifies both parties.
  - Beat task `expire_attestation_clarifications` in `attestation_beat.py`; schedule entry `"expire-attestation-clarifications-hourly"` (3600.0).
- Modifies: `matching_service.revoke_overdue_attestations` selection from `status == "accepted"` to `status IN ("accepted","in_review")` **and** applies the grace window (see §4.8). Grace is added here so overdue selection uses `completion_due_at + grace < now`.

- [ ] **Step 1: Write the failing tests**

Clarification expiry unit test:

```python
async def test_expire_closes_overdue_open(db_session) -> None:
    """An open clarification past its due time is expired by the sweep."""
    attestor, attestation = await _in_review_attestation(db_session)
    now = datetime.now(UTC)
    clar = await clarification_service.send_clarification(
        db_session, attestor=attestor, attestation_id=attestation.id,
        question="q", now=now - timedelta(hours=49),
    )
    count = await clarification_service.expire_clarifications(db_session, now=now)
    refreshed = await db_session.get(type(clar), clar.id)
    assert count == 1
    assert refreshed.status == "expired"
```

Revoke-beat widening unit test (add to `tests/unit/modules/test_attestation_matching_ranking.py` or a matching-service test file that already seeds attestations — assert an overdue `in_review` past `completion_due_at + grace` is revoked, and one within grace is not). Registration assertion in `test_attestation_beat_tasks.py`:

```python
def test_clarification_expiry_task_is_registered_in_beat_schedule() -> None:
    """Celery Beat includes the hourly clarification-expiry task."""
    schedule = BEAT_SCHEDULE["expire-attestation-clarifications-hourly"]
    assert schedule["task"] == (
        "app.workers.tasks.attestation_beat.expire_attestation_clarifications"
    )
    assert schedule["schedule"] == 3600.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/modules/test_attestation_clarifications.py -k expire tests/unit/workers/test_attestation_beat_tasks.py -k clarification -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

3a. Append `expire_clarifications` to `clarification_service.py`:

```python
async def expire_clarifications(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Close open clarifications past their response window. Returns count."""
    current_time = now or datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    overdue_ids = list(
        (
            await db.execute(
                select(AttestationClarification.id).where(
                    AttestationClarification.status == "open",
                    AttestationClarification.response_due_at <= current_time,
                )
            )
        ).scalars().all()
    )
    expired = 0
    for clarification_id in overdue_ids:
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            clarification = await db.scalar(
                select(AttestationClarification)
                .where(AttestationClarification.id == clarification_id)
                .with_for_update()
            )
            if clarification is None or clarification.status != "open":
                continue
            clarification.status = "expired"
            clarification.responded_at = current_time
            attestation = await db.get(Attestation, clarification.attestation_id)
            await write_audit(
                db=db,
                actor_id=None,
                action="attestation_clarification_expired",
                target_type="attestation",
                target_id=clarification.attestation_id,
                metadata={"clarification_id": str(clarification.id)},
            )
        expired += 1
        if attestation is not None and attestation.attestor_id is not None:
            attestation_notifications.notify_clarification_answered(
                attestation, attestor_id=attestation.attestor_id
            )
    return expired
```

3b. In `matching_service.py`, add a grace helper and widen selection. Add constant + change the query in `revoke_overdue_attestations`:

```python
DEFAULT_COMPLETION_GRACE_HOURS = 24
```

Replace the overdue selection so it reads (grace-aware, both statuses):

```python
        grace_hours = await _platform_int_config(
            db,
            key="attestation_completion_grace_hours",
            default=DEFAULT_COMPLETION_GRACE_HOURS,
            minimum=0,
        )
        cutoff = current_time - timedelta(hours=grace_hours)
        overdue_ids = list(
            (
                await db.execute(
                    select(Attestation.id).where(
                        Attestation.status.in_(("accepted", "in_review")),
                        Attestation.completion_due_at.is_not(None),
                        Attestation.completion_due_at <= cutoff,
                    )
                )
            ).scalars().all()
        )
```

And in the per-row re-check inside the lock, widen the guard from `status != "accepted"` to `status not in ("accepted", "in_review")` and compare against `cutoff` rather than `current_time`. (`_platform_int_config` already lives in this module; `timedelta` is imported.) Note: `minimum=0` because grace may legitimately be zero.

3c. In `attestation_beat.py`, add the helper + task (mirror `_revoke_overdue_attestations` / its wrapper):

```python
async def _expire_attestation_clarifications() -> int:
    """Close clarifications whose Requestor response window has elapsed."""
    async with async_session_factory() as db:
        return await clarification_service.expire_clarifications(db)
```

```python
@app.task(bind=True)
def expire_attestation_clarifications(self: Any) -> dict[str, int]:
    """Beat task: expire overdue open Attestation clarifications."""
    log = logger.bind(
        module="attestation",
        action="expire_attestation_clarifications",
        task_id=self.request.id,
    )
    log.info("task_started")
    expired_count = run_async(_expire_attestation_clarifications())
    log.info("task_completed", expired_count=expired_count)
    return {"expired_count": expired_count}
```

Import `clarification_service` in `attestation_beat.py`'s existing `from app.modules.attestation import ...` line.

3d. In `beat_schedule.py`, add after the revoke entry:

```python
    "expire-attestation-clarifications-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_attestation_clarifications",
        "schedule": 3600.0,
    },
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/modules/test_attestation_clarifications.py tests/unit/workers/test_attestation_beat_tasks.py tests/unit/modules/test_attestation_matching_ranking.py -v`
Expected: PASS (including the pre-existing revoke tests — confirm they still pass with the grace change; if a pre-existing test assumed instant revoke at `completion_due_at`, update it to account for the 24h grace and note it in the review ledger).

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/clarification_service.py app/modules/attestation/matching_service.py app/workers/tasks/attestation_beat.py app/workers/beat_schedule.py tests/
git commit -m "feat(attestation): clarification expiry sweep and grace-aware overdue revoke"
```

## Task 13: Clarification endpoints + OpenAPI + Slice-3 gate

**Files:**
- Modify: `app/modules/attestation/schemas.py`, `app/modules/attestation/router.py`, `contracts/openapi.yaml`
- Test: `tests/integration/test_attestation_clarifications.py`

**Interfaces:**
- Produces schemas `ClarificationCreateRequest(question: str)`, `ClarificationRespondRequest(response: str)`, `ClarificationResponse`. Endpoints:
  - `POST /v1/attestations/{attestation_id}/clarifications` (`ApprovedAttestorUser`)
  - `POST /v1/attestations/{attestation_id}/clarifications/{clarification_id}/respond` (`CurrentUser` — Requestor; service enforces requestor identity)
  - `GET /v1/attestations/{attestation_id}/clarifications` (both parties may read; service restricts to attestor-or-requestor, else 404)

- [ ] **Step 1: Write the failing test**

Integration: attestor sends → 201; requestor responds → 200; a third party responding → 404; attestor cannot respond → 404; unauthenticated → 401. (Reuse workspace auth fixtures; add a requestor-token fixture.)

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/integration/test_attestation_clarifications.py -v` → FAIL.

- [ ] **Step 3: Write minimal implementation** — add schemas (follow Task 8 style), add three thin router endpoints calling `clarification_service.send_clarification` / `respond_to_clarification` / a `list_clarifications` read helper (add a small `list_clarifications(db, *, user, attestation_id)` to the service that allows attestor-or-requestor else 404). Update `contracts/openapi.yaml`. For the respond endpoint use the module's existing authenticated-user dependency (the same one other requestor-facing attestation endpoints use — check `router.py` imports; it is the `require_role`/current-user dependency already in use for requestor actions).

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/integration/test_attestation_clarifications.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/schemas.py app/modules/attestation/router.py app/modules/attestation/clarification_service.py contracts/openapi.yaml tests/integration/test_attestation_clarifications.py
git commit -m "feat(attestation): clarification endpoints"
```

- [ ] **Step 6: Slice-3 gate**

```bash
uv run pytest tests/unit/modules/test_attestation_clarifications.py tests/integration/test_attestation_clarifications.py tests/unit/workers/test_attestation_beat_tasks.py -v
uv run ruff check .
uv run mypy app
```
Expected: green.

---

# SLICE 4 — Submit quality gate + report generation

## Task 14: Quality gate function

**Files:**
- Create gate logic in `app/modules/attestation/report.py` (new helper section) — or a small `app/modules/attestation/quality_gate.py` if `report.py` grows past ~400 lines (implementer's call; keep one responsibility per file).
- Test: `tests/unit/modules/test_attestation_quality_gate.py`

**Interfaces:**
- Produces: `async def evaluate_quality_gate(db, *, attestation: Attestation, summary: str, scope: str, conditions: str | None, outcome: str) -> list[str]` — returns a list of human-readable failure messages (empty = pass). Checks §4.7 items 1–6 (see spec). Reads config for min-words + contact-info toggle.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the attestation submission quality gate (§4.7)."""

from __future__ import annotations

import pytest

from app.modules.attestation import quality_gate  # or report, if inlined

pytestmark = pytest.mark.asyncio


async def test_gate_passes_complete_approved(db_session) -> None:
    """A fully scored, sufficiently long approved submission passes."""
    attestation = await _in_review_with_full_quality_rubric(db_session, words=200)
    failures = await quality_gate.evaluate_quality_gate(
        db_session, attestation=attestation,
        summary="A" * 0 + _long_text(200), scope="In scope: all clauses.",
        conditions=None, outcome="approved",
    )
    assert failures == []


async def test_gate_flags_incomplete_rubric(db_session) -> None:
    """A missing dimension score is reported."""
    attestation = await _in_review_missing_one_score(db_session)
    failures = await quality_gate.evaluate_quality_gate(
        db_session, attestation=attestation, summary=_long_text(200),
        scope="s", conditions=None, outcome="approved",
    )
    assert any("dimension" in f.lower() for f in failures)


async def test_gate_requires_conditions_when_conditional(db_session) -> None:
    """conditional outcome without conditions text fails."""
    attestation = await _in_review_with_full_quality_rubric(db_session, words=200)
    await _add_annotation(db_session, attestation)  # non-approved needs >=1
    failures = await quality_gate.evaluate_quality_gate(
        db_session, attestation=attestation, summary=_long_text(200),
        scope="s", conditions=None, outcome="conditional",
    )
    assert any("condition" in f.lower() for f in failures)


async def test_gate_requires_annotation_when_rejected(db_session) -> None:
    """rejected outcome with zero annotations fails."""
    attestation = await _in_review_with_full_quality_rubric(db_session, words=200)
    failures = await quality_gate.evaluate_quality_gate(
        db_session, attestation=attestation, summary=_long_text(200),
        scope="s", conditions=None, outcome="rejected",
    )
    assert any("annotation" in f.lower() for f in failures)


async def test_gate_blocks_contact_info(db_session) -> None:
    """An email address in the report text is a prohibited-content failure."""
    attestation = await _in_review_with_full_quality_rubric(db_session, words=200)
    failures = await quality_gate.evaluate_quality_gate(
        db_session, attestation=attestation,
        summary=_long_text(200) + " reach me at a@b.com", scope="s",
        conditions=None, outcome="approved",
    )
    assert any("contact" in f.lower() for f in failures)


async def test_gate_blocks_open_clarification(db_session) -> None:
    """An open clarification blocks submission."""
    attestation = await _in_review_with_open_clarification(db_session)
    failures = await quality_gate.evaluate_quality_gate(
        db_session, attestation=attestation, summary=_long_text(200),
        scope="s", conditions=None, outcome="approved",
    )
    assert any("clarification" in f.lower() for f in failures)
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/unit/modules/test_attestation_quality_gate.py -v` → FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
"""Attestation submission quality gate (§4.7).

Runs six independent checks and returns every failure at once so the Attestor
can fix them in a single pass. Called inline by report.submit_report before any
state change.

Maps to: workflow-doc §4.7. Design spec §4.7.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationClarification,
    AttestationRubricDimension,
    AttestationRubricScore,
)
from app.modules.financials.models import PlatformConfig

DEFAULT_MIN_WORDS = 150
_CONTACT_PATTERNS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"https?://", re.IGNORECASE),  # url
    re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)"),  # phone-ish
)


async def _int_config(db: AsyncSession, key: str, default: int) -> int:
    """Read an int PlatformConfig value, falling back to default."""
    raw = await db.scalar(select(PlatformConfig.value).where(PlatformConfig.key == key))
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


async def _contact_check_enabled(db: AsyncSession) -> bool:
    """Whether the prohibited contact-info check is on (default on)."""
    raw = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "attestation_report_block_contact_info"
        )
    )
    return raw != "0"


async def evaluate_quality_gate(
    db: AsyncSession,
    *,
    attestation: Attestation,
    summary: str,
    scope: str,
    conditions: str | None,
    outcome: str,
) -> list[str]:
    """Return the list of quality-gate failures (empty means the submission passes)."""
    failures: list[str] = []

    # 1. Rubric completeness: every dimension scored 1-5 with a comment.
    dimensions = list(
        await db.scalars(
            select(AttestationRubricDimension).where(
                AttestationRubricDimension.review_type == attestation.review_type,
                AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
            )
        )
    )
    scores = {
        row.dimension_id: row
        for row in await db.scalars(
            select(AttestationRubricScore).where(
                AttestationRubricScore.attestation_id == attestation.id
            )
        )
    }
    comment_words = 0
    for dim in dimensions:
        row = scores.get(dim.id)
        if row is None or row.score is None or not (row.comment or "").strip():
            failures.append(f"Rubric dimension '{dim.label}' needs a score and comment.")
        elif row.comment:
            comment_words += len(row.comment.split())

    # 2. Conditions mandatory iff conditional.
    if outcome == "conditional" and not (conditions or "").strip():
        failures.append("A conditional outcome requires a conditions statement.")

    # 3. >=1 annotation for non-approved outcomes.
    annotation_count = await db.scalar(
        select(func.count()).select_from(AttestationAnnotation).where(
            AttestationAnnotation.attestation_id == attestation.id
        )
    )
    if outcome in ("conditional", "rejected") and not annotation_count:
        failures.append("A non-approved outcome requires at least one annotation.")

    # 4. Word count of comments + summary + conditions.
    min_words = await _int_config(db, "attestation_report_min_words", DEFAULT_MIN_WORDS)
    total_words = comment_words + len(summary.split()) + len((conditions or "").split())
    if total_words < min_words:
        failures.append(
            f"Report is too short: {total_words} words (minimum {min_words})."
        )

    # 5. Prohibited content: no contact info.
    if await _contact_check_enabled(db):
        blob = " ".join(
            [summary, scope, conditions or ""]
            + [(row.comment or "") for row in scores.values()]
        )
        if any(pat.search(blob) for pat in _CONTACT_PATTERNS):
            failures.append(
                "Report contains contact information; communicate via the platform."
            )

    # 6. No open clarification.
    open_clar = await db.scalar(
        select(func.count()).select_from(AttestationClarification).where(
            AttestationClarification.attestation_id == attestation.id,
            AttestationClarification.status == "open",
        )
    )
    if open_clar:
        failures.append("Resolve the open clarification before submitting.")

    return failures
```

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/unit/modules/test_attestation_quality_gate.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/quality_gate.py tests/unit/modules/test_attestation_quality_gate.py
git commit -m "feat(attestation): submission quality gate with itemized failures"
```

## Task 15: Wire the gate + conditions + late-stamp + rubric_version into submit

**Files:**
- Modify: `app/modules/attestation/report.py`, `app/modules/attestation/schemas.py`
- Test: `tests/integration/test_attestation_clarifications.py` or a new `tests/integration/test_attestation_submit.py`

**Interfaces:**
- Modifies `submit_report`: precondition `allowed_statuses={"in_review"}`; add `conditions` to `AttestationReportSubmitRequest`; run `evaluate_quality_gate` → 422 with `detail=failures` on any failure; on pass set `conditions`, `rubric_version = rubrics.RUBRIC_VERSION`; late handling: if `now > completion_due_at` (and within grace, guaranteed by the still-`in_review` state) set `submitted_late=True`, increment the assignee's `AttestorProfile.late_submission_count`, audit `attestation_late_submission`.

- [ ] **Step 1: Write the failing test**

```python
async def test_submit_blocked_by_incomplete_rubric_returns_422(...):
    """Submitting with an unscored dimension returns 422 listing the gap."""
    ...
    assert resp.status_code == 422
    assert any("dimension" in m.lower() for m in resp.json()["detail"])


async def test_submit_past_deadline_within_grace_stamps_late(...):
    """Submitting after completion_due_at but within grace marks late + counter."""
    ...
    assert attestation.submitted_late is True
    assert profile.late_submission_count == 1
```

- [ ] **Step 2: Run to verify it fails** — FAIL (gate not wired, `conditions` field missing).

- [ ] **Step 3: Write minimal implementation**

3a. `schemas.py` — add to `AttestationReportSubmitRequest`:

```python
    conditions: str | None = Field(default=None, max_length=10000)
```

3b. `report.py` `submit_report` — change `allowed_statuses={"accepted"}` → `{"in_review"}`; after loading the attestation and before mutating, run the gate; add late handling. Insert:

```python
        failures = await evaluate_quality_gate(
            db,
            attestation=attestation,
            summary=payload.summary,
            scope=payload.scope,
            conditions=payload.conditions,
            outcome=payload.outcome,
        )
        if failures:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=failures,
            )
```

and in the mutation block add:

```python
        attestation.conditions = payload.conditions
        attestation.rubric_version = rubrics.RUBRIC_VERSION
        if (
            attestation.completion_due_at is not None
            and now > attestation.completion_due_at
        ):
            attestation.submitted_late = True
            profile = await db.scalar(
                select(AttestorProfile)
                .where(AttestorProfile.user_id == attestor_id)
                .with_for_update()
            )
            if profile is not None:
                profile.late_submission_count += 1
            await write_audit(
                db=db,
                actor_id=attestor_id,
                action="attestation_late_submission",
                target_type="attestation",
                target_id=attestation.id,
                metadata={"submitted_late": True},
            )
```

Import `evaluate_quality_gate`, `rubrics`, and `AttestorProfile` at the top of `report.py`. Note: `status` (fastapi) and `select` already imported.

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/report.py app/modules/attestation/schemas.py tests/integration/test_attestation_submit.py
git commit -m "feat(attestation): gate report submission, stamp conditions and late flag"
```

## Task 16: Grow report PDF to eight sections

**Files:**
- Modify: `app/workers/tasks/attestation_pdf.py`
- Test: `tests/unit/workers/test_attestation_pdf.py` (create or append — assert rendered HTML contains each section heading + a dimension label + weighted score)

**Interfaces:**
- Modifies `_render_attestation_report_pdf` to also load rubric scores (join dimensions), annotations, methodology, and `AttestorProfile.verification_level`; grows `REPORT_TEMPLATE` to §4.6's eight sections. Weighted overall computed via `rubrics.weighted_overall` using the stored `rubric_version` (fall back to `RUBRIC_VERSION` if null on legacy rows).

- [ ] **Step 1: Write the failing test**

Test the render helper against a seeded submitted attestation with full rubric + one annotation; assert the returned HTML/bytes contain "Methodology", "Dimension Scores", "Key Findings", a dimension label ("Completeness"), and "Overall Determination". (Render to HTML string by factoring the template render into a testable `_build_report_html(context)` returning the HTML before WeasyPrint — assert on that string to avoid PDF binary parsing.)

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Write minimal implementation**

Extend the data-loading query to fetch rubric score rows joined to `AttestationRubricDimension` (ordered by `display_order`), annotations (ordered by `created_at`), and the methodology row for `(review_type, rubric_version)`. Build a context dict with: `exec_summary=summary`, `scope`, `methodology=text_body`, `dimensions=[{label, weight, score, comment}]`, `weighted_overall`, `findings=[{type, location_label, quoted_excerpt, comment}]`, `conditions` (only when `outcome=="conditional"`), `determination=outcome`, `attestor_name`, `verification_level`, `issued_at`. Grow `REPORT_TEMPLATE` with the eight `<h2>` sections consuming that context (loop over `dimensions` and `findings`). Keep autoescape on. Factor the HTML build into `_build_report_html(context: dict) -> str` and call `HTML(string=_build_report_html(context))`.

- [ ] **Step 4: Run to verify it passes** — PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workers/tasks/attestation_pdf.py tests/unit/workers/test_attestation_pdf.py
git commit -m "feat(attestation): eight-section attestation report PDF"
```

## Task 17: Slice-4 + full-module gate

- [ ] **Step 1: Run the full Module 4 suite + repo gates**

```bash
uv run pytest tests/unit/modules/test_attestation_rubrics.py tests/unit/modules/test_attestation_workspace.py tests/unit/modules/test_attestation_clarifications.py tests/unit/modules/test_attestation_quality_gate.py tests/integration/test_attestation_workspace.py tests/integration/test_attestation_clarifications.py tests/integration/test_attestation_submit.py tests/unit/workers/test_attestation_beat_tasks.py tests/unit/workers/test_attestation_pdf.py -v
uv run ruff check .
uv run mypy app
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: all green; migration round-trip clean.

- [ ] **Step 2: Run the broader attestation regression** to confirm no Module 1/2/3 breakage from the `in_review` enum + grace change:

```bash
uv run pytest tests/unit/modules/test_attestation_matching_ranking.py tests/integration/test_attestation_offers.py tests/integration/test_attestation_matching.py -v
```
Expected: green (update any test that assumed instant revoke at `completion_due_at` to account for the 24h grace; record it in the review ledger).

- [ ] **Step 3:** Slice 4 done — hand to final whole-branch review.

---

## Self-review notes (planner)

- **Spec coverage:** §3.1 (Task 2/3), §3.2–3.3 columns (Task 2/3), §3.4 rubric tables + seed (Task 1/3), §3.5 scores (Task 2/6), §3.6 annotations (Task 2/7), §3.7 clarifications (Task 2/10-12), §4.1 start-review (Task 5/8), §4.2 rubric CRUD (Task 6/8), §4.3 annotations (Task 7/8), §4.4 clarification pause (Task 10-13), §4.5 determination (Task 15), §4.6 8-section report (Task 16), §4.7 gate (Task 14-15), §4.8 grace-then-revoke (Task 12/15), §5 security 404/RBAC/audit (Tasks 5,11,13). All covered.
- **Cross-task type consistency:** `load_workspace_attestation`, `evaluate_quality_gate`, `weighted_overall`, `send_clarification`/`respond_to_clarification`/`expire_clarifications` signatures are defined once and reused verbatim by callers.
- **Test helper reuse:** several tasks reference shared seed helpers (`_in_review_attestation`, `_accepted_attestation`, etc.). Task 5 introduces them in `tests/integration/test_attestation_workspace.py`; later test files import or re-declare minimal variants following the same pattern as existing attestation integration tests. The implementer defines each helper the first time a slice's test file needs it.
- **Open item for the reviewer:** the grace-window change to `revoke_overdue_attestations` alters Module 3 behavior (instant → +24h). Confirm no production assumption depends on instant revoke; it is a spec-mandated §4.8 change and must be called out in the Module 4 review ledger.
