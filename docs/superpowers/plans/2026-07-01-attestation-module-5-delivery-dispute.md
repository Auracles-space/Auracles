# Attestation Module 5 — Delivery, Acceptance & Dispute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the attestation completion loop — deliver report on a 5-business-day window, capture a 1–5 rating, run the full dispute lifecycle (categories, evidence, revise-resubmit, warnings, suspension-review, SLA clock), and stamp publication eligibility for Module 6.

**Architecture:** Backend-only, extends the existing `report` / `release_service` / `dispute_service` modules in place. No new escrow math (release stays 100%-to-attestor; 90/10 split is Module 6). New shared `add_business_days` util, two new tables (`attestation_ratings`, `attestor_warnings`), two new enums, and status/column additions. Every slice is one Alembic migration + service + schema + router + OpenAPI, TDD RED→GREEN per behavior.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, PostgreSQL 16, Celery + Beat, loguru, `uv`, pytest / pytest-asyncio, freezegun. All commands run from `backend/`.

## Global Constraints

- **Spec is binding:** `docs/superpowers/specs/2026-07-01-attestation-module-5-delivery-dispute-design.md`. Every decision table row is a requirement.
- **M5/M6 boundary:** M5 fires escrow *release* (100% to attestor, unchanged) and *refund* (existing path). NO 90/10 split, NO badge publication, NO reputation scoring — those are Module 6.
- **Business-day math:** weekends-only (skip Sat/Sun), no holidays, UTC. Single util `add_business_days`.
- **Dispute window default:** 5 business days. Config key `attestation_dispute_window_business_days` (renamed from `attestation_dispute_window_days`).
- **Evidence min-length default:** config `attestation_dispute_evidence_min_length`, default 40 chars. Below → 422 (this IS the vexatious guard).
- **Revision SLA default:** config `attestation_revision_sla_business_days`, default 5.
- **Resolution SLA:** 5 business days standard, 15 if `is_complex` (admin-set). No auto-resolve.
- **Requestor-flag threshold:** ≥ 3 rejected disputes in rolling 12 months. Derived, never stored. Expose as boolean only.
- **Suspension-review threshold:** ≥ 2 upheld-dispute warnings in rolling 12 months. Derived. Flag + notify admin, NEVER auto-deactivate.
- **`split` resolution is removed** — deliberate deletion of shipped code, tests, columns, and enum. Reviewer/human attention required.
- **Security (CLAUDE.md):** Pydantic on every input; RBAC via dependency; admin dispute-resolve stays admin + TOTP; existence-hiding 404 on ownership mismatch; refund does Stripe refund before local state change; audit every state-changing action; no secrets/PII in logs; `requestor_flagged` exposes boolean only.
- **Docstrings:** Google-style module/class/function docstrings on every new file/function (CLAUDE.md doc standard). Map each to its FR/§ where relevant.
- **Migrations:** one per slice, filename `YYYY_MM_DD_NNNN_description.py`, revision id = date+seq (e.g. `2026_07_01_0049`), chained from `2026_07_01_0048`. Both `alembic upgrade head` and `alembic downgrade -1` must succeed. No column/type drop without the human review the split-removal calls out.
- **Coverage:** ≥ 80% line coverage on touched `app/modules/**` and `app/workers/**`.
- **Commit style:** commit on `main` after each task (per repo convention). No `Co-Authored-By` trailer. Commit message ends at last meaningful line.
- **Gate before "clean":** `uv run pytest <touched test files>`, then whole-repo `uv run ruff check .` and `uv run mypy app` — all from `backend/`.
- **Migration-test batch quirk:** migration-only tests may fail when batched with other DB tests (shared-DB downgrade/upgrade); run them isolated and exclude from batched gate runs via `-k "... and not migration"` (Module 4 convention).

---

## File Structure

**New files:**
- `app/shared/business_days.py` — pure `add_business_days` util (Slice 1).
- `app/modules/attestation/rating_service.py` — rating capture service (Slice 2).
- `tests/unit/shared/test_business_days.py` (Slice 1).
- `tests/unit/modules/test_attestation_rating.py` (Slice 2).
- `tests/unit/modules/test_attestation_dispute_intake.py` (Slice 3).
- `tests/unit/modules/test_attestation_resolution.py` (Slice 4).
- `tests/unit/modules/test_attestation_warnings.py` (Slice 5).
- `tests/integration/test_attestation_rating_endpoints.py` (Slice 2).
- Migration per slice under `migrations/versions/`.

**Modified files:**
- `app/modules/attestation/models.py` — new tables, enums, columns (Slices 2–5).
- `app/modules/attestation/report.py` — business-day window + `revision_requested` precondition (Slices 1, 4).
- `app/modules/attestation/release_service.py` — `report_published_eligible` stamp (Slice 4).
- `app/modules/attestation/dispute_service.py` — category/evidence intake, outcome restructure, revise-resubmit, warnings, SLA clock (Slices 3–5).
- `app/modules/attestation/rating_service.py` (new) + `router.py` — rating endpoint (Slice 2).
- `app/modules/attestation/schemas.py` — dispute request/response, resolve request, rating schemas, `requestor_flagged` on assignment (Slices 2–5).
- `app/modules/attestation/matching_service.py` — populate `requestor_flagged` on assignment payload + requestor-flag helper (Slice 3).
- `app/modules/attestation/notifications.py` — new notify fns (Slices 4–5).
- `app/workers/tasks/attestation_beat.py` + `app/workers/beat_schedule.py` — SLA-overdue flag task (Slice 5).
- `contracts/openapi.yaml` — new/changed endpoints (Slices 2–5).

---

## SLICE 1 — Business-day util + 5-business-day dispute window

### Task 1: `add_business_days` util

**Files:**
- Create: `app/shared/business_days.py`
- Test: `tests/unit/shared/test_business_days.py`

**Interfaces:**
- Produces: `add_business_days(start: datetime, business_days: int) -> datetime` — returns a timezone-aware UTC datetime `business_days` weekdays after `start`, preserving `start`'s time-of-day. Skips Saturday/Sunday. `business_days` must be ≥ 0; `business_days == 0` returns `start` unchanged (normalized to UTC). Raises `ValueError` on negative input.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/shared/test_business_days.py
"""Unit tests for the weekend-only business-day helper."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.shared.business_days import add_business_days


def test_friday_plus_one_is_monday() -> None:
    """One business day after a Friday lands on the following Monday."""
    friday = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)  # 2026-07-03 is a Friday
    assert add_business_days(friday, 1) == datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def test_five_business_days_skips_one_weekend() -> None:
    """Five business days from Monday lands on the next Monday."""
    monday = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    assert add_business_days(monday, 5) == datetime(2026, 7, 13, 9, 0, tzinfo=UTC)


def test_saturday_start_first_business_day_is_monday() -> None:
    """Counting from a weekend advances into Monday for the first day."""
    saturday = datetime(2026, 7, 4, 8, 0, tzinfo=UTC)  # Saturday
    assert add_business_days(saturday, 1) == datetime(2026, 7, 6, 8, 0, tzinfo=UTC)


def test_zero_business_days_returns_start_in_utc() -> None:
    """Zero business days returns the start moment normalized to UTC."""
    start = datetime(2026, 7, 6, 10, 30, tzinfo=UTC)
    assert add_business_days(start, 0) == start


def test_negative_raises() -> None:
    """A negative business-day count is rejected."""
    with pytest.raises(ValueError):
        add_business_days(datetime(2026, 7, 6, tzinfo=UTC), -1)
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/unit/shared/test_business_days.py -v`
Expected: FAIL — `ModuleNotFoundError: app.shared.business_days`.

- [ ] **Step 3: Implement the util**

```python
# app/shared/business_days.py
"""Weekend-only business-day arithmetic.

Provides the single helper used across the Attestation delivery/dispute flow
to compute business-day deadlines (dispute window, revision SLA, resolution
SLA). Weekends (Saturday/Sunday) are skipped; no holiday calendar is applied.
All arithmetic is anchored in UTC.

Maps to: Module 5 design spec section 4.1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

SATURDAY = 5
SUNDAY = 6


def add_business_days(start: datetime, business_days: int) -> datetime:
    """Return the datetime ``business_days`` weekdays after ``start`` (UTC).

    Skips Saturday and Sunday. Preserves ``start``'s time-of-day. A count of
    zero returns ``start`` normalized to UTC.

    Args:
        start: The reference moment. Naive datetimes are treated as UTC.
        business_days: Non-negative number of weekdays to add.

    Returns:
        A timezone-aware UTC datetime.

    Raises:
        ValueError: If ``business_days`` is negative.
    """
    if business_days < 0:
        raise ValueError("business_days must be non-negative.")
    current = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
    remaining = business_days
    while remaining > 0:
        current = current + timedelta(days=1)
        if current.weekday() not in (SATURDAY, SUNDAY):
            remaining -= 1
    return current
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/shared/test_business_days.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/shared/business_days.py tests/unit/shared/test_business_days.py
git commit -m "Add weekend-only add_business_days util for attestation SLAs"
```

### Task 2: 5-business-day dispute window at report submit + config rename

**Files:**
- Modify: `app/modules/attestation/report.py:41` (`DEFAULT_DISPUTE_WINDOW_DAYS`), `:161-175` (window compute)
- Create: `migrations/versions/2026_07_01_0049_dispute_window_business_days.py`
- Test: `tests/unit/modules/test_attestation_submit.py` (extend — existing Module 4 file)

**Interfaces:**
- Consumes: `add_business_days` (Task 1).
- Produces: config key `attestation_dispute_window_business_days` (int, default 5); constant `DEFAULT_DISPUTE_WINDOW_BUSINESS_DAYS = 5`.

- [ ] **Step 1: Write the failing test** — add to `tests/unit/modules/test_attestation_submit.py`:

```python
async def test_submit_sets_business_day_dispute_window(db_session, frozen_monday) -> None:
    """Report submit sets dispute_window_ends_at 5 business days out.

    Enforces Module 5 spec section 4.2 (weekend-skipping window).
    """
    # frozen_monday: freezegun-frozen at 2026-07-06 12:00 UTC (a Monday).
    attestation = await _submit_ready_quality_attestation(db_session)  # in_review, full rubric
    result = await report.submit_report(
        db=db_session,
        attestor=attestation.attestor_user,
        attestation_id=attestation.id,
        payload=_valid_submit_payload(outcome="approved"),
    )
    # 5 business days from Mon 2026-07-06 == Mon 2026-07-13.
    assert result.dispute_window_ends_at == datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
```

> Reuse the existing submit-test fixtures/helpers in this file (Module 4 added `_submit_ready...` style helpers and a rubric seeder). If a `frozen_monday` fixture does not exist, add one with `freezegun.freeze_time("2026-07-06T12:00:00Z")`.

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/unit/modules/test_attestation_submit.py::test_submit_sets_business_day_dispute_window -v`
Expected: FAIL — window computed as `now + 14 calendar days` ≠ `2026-07-13`.

- [ ] **Step 3: Implement** — edit `app/modules/attestation/report.py`:

Replace line 41:
```python
DEFAULT_DISPUTE_WINDOW_BUSINESS_DAYS = 5
```
Add import near the top (with the other `app.` imports):
```python
from app.shared.business_days import add_business_days
```
Replace the window block (currently lines ~161-175):
```python
        dispute_window_business_days = await _platform_int_config(
            db,
            key="attestation_dispute_window_business_days",
            default=DEFAULT_DISPUTE_WINDOW_BUSINESS_DAYS,
            minimum=1,
        )
        attestation.status = "report_submitted"
        attestation.outcome = payload.outcome
        attestation.summary = payload.summary
        attestation.scope = payload.scope
        attestation.conditions = payload.conditions
        attestation.evidence_references = payload.evidence_references
        attestation.report_key = report_key
        attestation.issued_at = now
        attestation.dispute_window_ends_at = add_business_days(
            now, dispute_window_business_days
        )
        attestation.rubric_version = rubrics.RUBRIC_VERSION
```
Remove the now-unused `timedelta` usage for the window (keep `timedelta` import if still used elsewhere in the file — it is, for the upload TTL).

- [ ] **Step 4: Write the migration** — `migrations/versions/2026_07_01_0049_dispute_window_business_days.py`:

```python
"""Rename dispute-window config to business days and reseed the default.

Module 5 changes the dispute window from 14 calendar days to 5 business days.
The config key is renamed to make the semantics explicit and to stop a stale
calendar value from leaking in. In-flight rows keep their existing
dispute_window_ends_at timestamps (auto-release reads the timestamp, not the
config), so no data backfill is performed.

Maps to: Module 5 design spec section 4.2 / 4.9 (window migration).

Revision ID: 2026_07_01_0049
Revises: 2026_07_01_0048
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_01_0049"
down_revision: str | Sequence[str] | None = "2026_07_01_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the calendar-day window config row with the business-day key."""
    op.execute(
        "DELETE FROM platform_config WHERE key = 'attestation_dispute_window_days'"
    )
    op.execute(
        "INSERT INTO platform_config (key, value) "
        "VALUES ('attestation_dispute_window_business_days', '5') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    """Restore the calendar-day window config key."""
    op.execute(
        "DELETE FROM platform_config "
        "WHERE key = 'attestation_dispute_window_business_days'"
    )
    op.execute(
        "INSERT INTO platform_config (key, value) "
        "VALUES ('attestation_dispute_window_days', '14') "
        "ON CONFLICT (key) DO NOTHING"
    )
```

> Verify the `platform_config` table + columns (`key`, `value`) and any seed pattern by checking `app/modules/financials/models.py` (`PlatformConfig`) and how other config rows are seeded. Adjust column names if the real schema differs. If PlatformConfig has no rows seeded by default (the code falls back to the constant default), the DELETE/INSERT is still safe.

- [ ] **Step 5: Run migration + test**

Run:
```bash
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
uv run pytest tests/unit/modules/test_attestation_submit.py -v
```
Expected: migrations succeed both directions; submit tests pass (existing + new window test).

- [ ] **Step 6: Commit**

```bash
git add app/modules/attestation/report.py migrations/versions/2026_07_01_0049_dispute_window_business_days.py tests/unit/modules/test_attestation_submit.py
git commit -m "Switch attestation dispute window to 5 business days"
```

---

## SLICE 2 — Rating capture

### Task 3: `AttestationRating` model + migration

**Files:**
- Modify: `app/modules/attestation/models.py` (add `AttestationRating` class after `AttestationDispute`)
- Create: `migrations/versions/2026_07_01_0050_attestation_ratings.py`

**Interfaces:**
- Produces: `AttestationRating` ORM model — table `attestation_ratings`, columns `id` (uuid pk), `attestation_id` (uuid fk `attestations.id` ondelete CASCADE, **unique**), `rated_by` (uuid fk `users.id`), `stars` (int, check 1–5), `comment` (text nullable), `created_at` (timestamptz, server_default now()).

- [ ] **Step 1: Write the failing test** — new `tests/unit/modules/test_attestation_rating.py`, first test asserts the model persists and the unique constraint holds:

```python
"""Unit tests for attestation rating capture (Module 5 section 5.3)."""

from __future__ import annotations

# ... imports mirroring tests/unit/modules/test_attestation_quality_gate.py
# (async_session_factory, migrated_database/clean_state/db_session fixtures,
#  _make_user, a helper to create a closed report-stood attestation).

async def test_rating_row_persists_and_is_unique(db_session) -> None:
    """One rating per attestation; a duplicate insert violates the unique key."""
    attestation = await _closed_after_accept(db_session)  # released via accept
    db_session.add(
        AttestationRating(
            attestation_id=attestation.id,
            rated_by=attestation.requestor_id,
            stars=5,
            comment="Thorough.",
        )
    )
    await db_session.commit()
    db_session.add(
        AttestationRating(
            attestation_id=attestation.id,
            rated_by=attestation.requestor_id,
            stars=4,
            comment=None,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

- [ ] **Step 2: Run to verify fail** — `ImportError: AttestationRating`.

- [ ] **Step 3: Implement the model** — add to `app/modules/attestation/models.py`:

```python
class AttestationRating(Base):
    """Requestor's 1-5 quality rating of a stood attestation report.

    One immutable rating per attestation. Stored in Module 5; consumed by
    Module 6.4 reputation scoring. Maps to workflow section 5.3.
    """

    __tablename__ = "attestation_ratings"
    __table_args__ = (
        UniqueConstraint(
            "attestation_id", name="uq_attestation_ratings_attestation"
        ),
        CheckConstraint(
            "stars BETWEEN 1 AND 5", name="ck_attestation_ratings_stars_range"
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
    rated_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
```

- [ ] **Step 4: Write the migration** — `2026_07_01_0050_attestation_ratings.py`, `down_revision = "2026_07_01_0049"`, `op.create_table("attestation_ratings", ...)` mirroring the columns/constraints above; `downgrade` drops the table. Follow the `create_table` style used in `2026_07_01_0048`.

- [ ] **Step 5: Run migration + test**

```bash
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
uv run pytest tests/unit/modules/test_attestation_rating.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/attestation/models.py migrations/versions/2026_07_01_0050_attestation_ratings.py tests/unit/modules/test_attestation_rating.py
git commit -m "Add attestation_ratings table"
```

### Task 4: rating service (eligibility + immutability)

**Files:**
- Create: `app/modules/attestation/rating_service.py`
- Test: `tests/unit/modules/test_attestation_rating.py` (extend)

**Interfaces:**
- Consumes: `AttestationRating`, `Attestation`, `User`.
- Produces: `async def submit_rating(*, db, requestor: User, attestation_id: UUID, stars: int, comment: str | None) -> AttestationRating`.

**Eligibility rules (spec §4.3):** requestor must own the attestation (else 404, existence-hiding); attestation must be in a *report-stood terminal* state — `closed` reached via accept/auto-accept **or** dispute-`rejected`. Refunded/CoI-upheld → **not** eligible (409). One rating per attestation (duplicate → 409). Stars validated 1–5 by the schema; service re-checks defensively.

Report-stood detection: `attestation.report_published_eligible is True` is the single flag introduced in Slice 4. **Ordering note:** this service ships in Slice 2 but the `report_published_eligible` flag lands in Slice 4. To keep Slice 2 independently testable, gate eligibility in Slice 2 on `attestation.status == "closed"` AND no `upheld_refund`/refunded outcome; then in Slice 4 Task 15, tighten it to read `report_published_eligible`. Both are specified below; implement the Slice-2 form now.

- [ ] **Step 1: Write the failing tests** (eligibility matrix):

```python
async def test_requestor_rates_closed_accepted_report(db_session) -> None:
    """A requestor can rate a report that stood via acceptance."""
    attestation = await _closed_after_accept(db_session)
    rating = await rating_service.submit_rating(
        db=db_session,
        requestor=await db_session.get(User, attestation.requestor_id),
        attestation_id=attestation.id,
        stars=5,
        comment="Clear and rigorous.",
    )
    assert rating.stars == 5


async def test_duplicate_rating_conflicts(db_session) -> None:
    """A second rating on the same attestation is rejected 409."""
    attestation = await _closed_after_accept(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    await rating_service.submit_rating(
        db=db_session, requestor=requestor,
        attestation_id=attestation.id, stars=4, comment=None,
    )
    with pytest.raises(HTTPException) as exc:
        await rating_service.submit_rating(
            db=db_session, requestor=requestor,
            attestation_id=attestation.id, stars=3, comment=None,
        )
    assert exc.value.status_code == 409


async def test_non_requestor_gets_404(db_session) -> None:
    """A non-requestor cannot rate; existence is hidden with 404."""
    attestation = await _closed_after_accept(db_session)
    stranger = await _make_user("operator", "stranger")
    with pytest.raises(HTTPException) as exc:
        await rating_service.submit_rating(
            db=db_session, requestor=stranger,
            attestation_id=attestation.id, stars=5, comment=None,
        )
    assert exc.value.status_code == 404


async def test_refunded_attestation_not_rateable(db_session) -> None:
    """A refunded (CoI-upheld) attestation's report did not stand — 409."""
    attestation = await _closed_after_refund(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    with pytest.raises(HTTPException) as exc:
        await rating_service.submit_rating(
            db=db_session, requestor=requestor,
            attestation_id=attestation.id, stars=5, comment=None,
        )
    assert exc.value.status_code == 409
```

- [ ] **Step 2: Run to verify fail** — `ModuleNotFoundError: rating_service`.

- [ ] **Step 3: Implement `rating_service.py`:**

```python
"""Attestation rating capture (Module 5 section 5.3).

Requestors rate a stood report 1-5 stars with an optional comment. The rating
is decoupled from escrow release (money never waits on a rating prompt), one
per attestation, immutable, and consumed later by Module 6 reputation scoring.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation.models import Attestation, AttestationRating
from app.modules.auth.models import User

# Terminal states in which the report "stood" and is thus rateable.
_RATEABLE_STATUSES = {"closed"}
# Attestation statuses/outcomes where the report did NOT stand.
_NON_STOOD_OUTCOMES = {"upheld_refund"}


async def submit_rating(
    *,
    db: AsyncSession,
    requestor: User,
    attestation_id: UUID,
    stars: int,
    comment: str | None,
) -> AttestationRating:
    """Record the requestor's immutable 1-5 rating of a stood report.

    Args:
        db: Async database session.
        requestor: Authenticated requestor (must own the attestation).
        attestation_id: Attestation whose report is being rated.
        stars: Integer 1-5 (validated at the schema; re-checked here).
        comment: Optional free-text comment.

    Returns:
        The persisted rating row.

    Raises:
        HTTPException(404): Attestation missing or not owned by the requestor.
        HTTPException(409): Report did not stand, or already rated.
        HTTPException(422): Stars outside 1-5.
    """
    if stars < 1 or stars > 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Rating must be between 1 and 5 stars.",
        )
    requestor_id = requestor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await db.scalar(
            select(Attestation)
            .where(Attestation.id == attestation_id)
            .with_for_update()
        )
        if attestation is None or attestation.requestor_id != requestor_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        if not _report_stood(attestation):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a stood attestation report can be rated.",
            )
        existing = await db.scalar(
            select(AttestationRating.id).where(
                AttestationRating.attestation_id == attestation.id
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation has already been rated.",
            )
        rating = AttestationRating(
            attestation_id=attestation.id,
            rated_by=requestor_id,
            stars=stars,
            comment=comment.strip() if comment else None,
        )
        db.add(rating)
        await write_audit(
            db=db,
            actor_id=requestor_id,
            action="attestation_rated",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"stars": stars},
        )
        await db.flush()
        await db.refresh(rating)
    return rating


def _report_stood(attestation: Attestation) -> bool:
    """Return whether the attestation's report stood and is thus rateable.

    Slice-2 form: closed AND not a refund/CoI-upheld outcome. Slice 4 (Task 15)
    tightens this to read ``attestation.report_published_eligible``.
    """
    if attestation.status not in _RATEABLE_STATUSES:
        return False
    outcome = getattr(attestation, "outcome", None)
    return outcome not in _NON_STOOD_OUTCOMES
```

> `_closed_after_refund` helper should set the attestation to a refunded/closed state that this predicate treats as non-stood. In Slice 2 (before `report_published_eligible` exists), model "refunded" by leaving the attestation `status="closed"` but flagging non-stood through a dispute row with the refund outcome — OR, simplest for Slice 2, use `status != "closed"` (e.g. `refunded`) so `_report_stood` returns False. Pick whichever the existing refund path produces; in Slice 4 this predicate is replaced by the explicit flag, removing ambiguity.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/unit/modules/test_attestation_rating.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/rating_service.py tests/unit/modules/test_attestation_rating.py
git commit -m "Add attestation rating service with eligibility rules"
```

### Task 5: rating endpoint + schema + OpenAPI

**Files:**
- Modify: `app/modules/attestation/schemas.py` (add `AttestationRatingCreateRequest`, `AttestationRatingResponse`)
- Modify: `app/modules/attestation/router.py` (add `POST /attestations/{id}/rating`)
- Modify: `contracts/openapi.yaml`
- Test: `tests/integration/test_attestation_rating_endpoints.py`

**Interfaces:**
- Consumes: `rating_service.submit_rating`.
- Produces: endpoint `POST /v1/attestations/{attestation_id}/rating` → `AttestationRatingResponse`.

- [ ] **Step 1: Write the failing integration tests** — happy (201), duplicate (409), non-requestor (404), wrong role (403), unauthenticated (401), stars out of range (422). Mirror the AsyncClient/auth-fixture patterns in `tests/integration/test_attestation_*` files.

```python
async def test_requestor_rates_report(client, requestor_headers, stood_attestation) -> None:
    resp = await client.post(
        f"/v1/attestations/{stood_attestation.id}/rating",
        json={"stars": 5, "comment": "Excellent."},
        headers=requestor_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["stars"] == 5
```

- [ ] **Step 2: Run to verify fail** — 404 route not found.

- [ ] **Step 3: Add schemas** — in `schemas.py`:

```python
class AttestationRatingCreateRequest(BaseModel):
    """Requestor's 1-5 rating of a stood attestation report."""

    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)


class AttestationRatingResponse(BaseModel):
    """Persisted attestation rating."""

    id: UUID
    attestation_id: UUID
    rated_by: UUID
    stars: int
    comment: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: Add router endpoint** — in `router.py` (import the new schemas + `rating_service`; add `RequestorUser` is already defined at line 131):

```python
@router.post(
    "/attestations/{attestation_id}/rating",
    response_model=AttestationRatingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Rate a stood attestation report",
    description="Record the requestor's one-time 1-5 rating of a stood report.",
)
async def rate_attestation_report(
    attestation_id: UUID,
    payload: AttestationRatingCreateRequest,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationRatingResponse:
    """Capture the requestor's immutable rating of a stood report."""
    rating = await rating_service.submit_rating(
        db=db,
        requestor=requestor,
        attestation_id=attestation_id,
        stars=payload.stars,
        comment=payload.comment,
    )
    return AttestationRatingResponse.model_validate(rating)
```
Add `rating_service` to the `from app.modules.attestation import (...)` block.

- [ ] **Step 5: Update `contracts/openapi.yaml`** — add the path + the two component schemas. Generate the exact shapes by running `python -c "import json,app.main; print(json.dumps(app.main.app.openapi()['paths']['/v1/attestations/{attestation_id}/rating']))"` (adjust prefix) and copy the request/response schemas verbatim so the contract matches FastAPI generation (Module 4's OpenAPI-drift lesson).

- [ ] **Step 6: Run tests** — `uv run pytest tests/integration/test_attestation_rating_endpoints.py -v` → PASS. Verify contract parses: `python -c "import yaml; yaml.safe_load(open('../contracts/openapi.yaml'))"`.

- [ ] **Step 7: Commit**

```bash
git add app/modules/attestation/schemas.py app/modules/attestation/router.py ../contracts/openapi.yaml tests/integration/test_attestation_rating_endpoints.py
git commit -m "Add attestation report rating endpoint"
```

---

## SLICE 3 — Dispute intake hardening

### Task 6: dispute category enum + evidence guard (model + migration)

**Files:**
- Modify: `app/modules/attestation/models.py` (add `ATTESTATION_DISPUTE_CATEGORY_ENUM`, `category` column on `AttestationDispute`, add index `(raised_by, status, resolved_at)`)
- Create: `migrations/versions/2026_07_01_0051_dispute_category.py`

**Interfaces:**
- Produces: enum `attestation_dispute_category_enum` (`scope_error`, `process_violation`, `material_inaccuracy`, `conflict_of_interest`); `AttestationDispute.category` (enum, not null); index `idx_attestation_disputes_raised_by_status_resolved`.

- [ ] **Step 1: Failing test** — assert a dispute row requires a category (DB not-null) — add to new `tests/unit/modules/test_attestation_dispute_intake.py`.

- [ ] **Step 2: Run fail.**

- [ ] **Step 3: Implement** — add the enum near the other attestation enums:

```python
ATTESTATION_DISPUTE_CATEGORY_ENUM = ENUM(
    "scope_error",
    "process_violation",
    "material_inaccuracy",
    "conflict_of_interest",
    name="attestation_dispute_category_enum",
    create_type=False,
)
```
Add to `AttestationDispute`:
```python
    category: Mapped[str] = mapped_column(
        ATTESTATION_DISPUTE_CATEGORY_ENUM,
        nullable=False,
    )
```
Add to `AttestationDispute.__table_args__`:
```python
        Index(
            "idx_attestation_disputes_raised_by_status_resolved",
            "raised_by",
            "status",
            "resolved_at",
        ),
```

- [ ] **Step 4: Migration** — `2026_07_01_0051`, `down_revision="2026_07_01_0050"`. Create the enum type (`postgresql.ENUM(..., create_type=False)` then `.create(bind, checkfirst=True)`), then add the `category` column. Because existing dispute rows (if any in the DB) have no category, add the column **nullable first**, backfill existing rows to `'material_inaccuracy'` (safe default for legacy free-text disputes), then `ALTER COLUMN ... SET NOT NULL`. Add the index. `downgrade`: drop index, drop column, drop enum type.

- [ ] **Step 5: Run migration up/down + tests.**

- [ ] **Step 6: Commit** `"Add attestation dispute category enum and abuse index"`.

### Task 7: evidence min-length guard + category in `create_dispute`

**Files:**
- Modify: `app/modules/attestation/dispute_service.py` (`create_dispute` signature/body, add `_evidence_min_length` config helper)
- Modify: `app/modules/attestation/schemas.py` (`AttestationDisputeCreateRequest` gains `category`; `AttestationDisputeResponse` gains `category`)
- Modify: `app/modules/attestation/router.py` (pass `category` through — already passes `payload`)
- Modify: `contracts/openapi.yaml`
- Test: `tests/unit/modules/test_attestation_dispute_intake.py`

**Interfaces:**
- Produces: config `attestation_dispute_evidence_min_length` (default 40); `create_dispute` now validates evidence length and stores `category`.

- [ ] **Step 1: Failing tests:**

```python
async def test_dispute_below_min_evidence_length_is_422(db_session) -> None:
    """Evidence shorter than the configured minimum is rejected (vexatious guard)."""
    attestation = await _report_submitted_within_window(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    with pytest.raises(HTTPException) as exc:
        await dispute_service.create_dispute(
            db=db_session, requestor=requestor, attestation_id=attestation.id,
            payload=AttestationDisputeCreateRequest(
                category="scope_error", reason="too short",
            ),
        )
    assert exc.value.status_code == 422


async def test_dispute_stores_category(db_session) -> None:
    """A valid dispute persists the chosen category."""
    attestation = await _report_submitted_within_window(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    dispute = await dispute_service.create_dispute(
        db=db_session, requestor=requestor, attestation_id=attestation.id,
        payload=AttestationDisputeCreateRequest(
            category="material_inaccuracy",
            reason="Finding 3 misstates the 2025 revenue by a factor of ten, see p.4.",
        ),
    )
    assert dispute.category == "material_inaccuracy"
```

- [ ] **Step 2: Run fail.**

- [ ] **Step 3: Implement:**

Schema (`schemas.py`) — replace `AttestationDisputeCreateRequest`:
```python
class AttestationDisputeCreateRequest(BaseModel):
    """Request body for raising an Attestation report dispute."""

    category: Literal[
        "scope_error",
        "process_violation",
        "material_inaccuracy",
        "conflict_of_interest",
    ]
    reason: str = Field(min_length=5, max_length=4000)
```
Add `category: str` to `AttestationDisputeResponse` (after `raised_by`).

Service (`dispute_service.py`) — add helper + wire into `create_dispute`:
```python
DEFAULT_DISPUTE_EVIDENCE_MIN_LENGTH = 40


async def _evidence_min_length(db: AsyncSession) -> int:
    """Return the configured minimum dispute-evidence character length."""
    return await _platform_int_config(
        db,
        key="attestation_dispute_evidence_min_length",
        default=DEFAULT_DISPUTE_EVIDENCE_MIN_LENGTH,
        minimum=1,
    )
```
Inside `create_dispute`, after loading + ownership + status + window checks, before building the dispute:
```python
        evidence = payload.reason.strip()
        min_length = await _evidence_min_length(db)
        if len(evidence) < min_length:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Dispute evidence is too short to substantiate the claim.",
            )
        await _reject_duplicate_active_dispute(db, attestation.id)
        dispute = AttestationDispute(
            attestation_id=attestation.id,
            raised_by=requestor_id,
            category=payload.category,
            reason=evidence,
        )
```

- [ ] **Step 4: OpenAPI** — regenerate the dispute-create request/response schemas into `contracts/openapi.yaml` (verify against `app.openapi()`).

- [ ] **Step 5: Run unit + existing dispute integration tests.** Existing dispute integration tests will now need a `category` in the request body — update them.

- [ ] **Step 6: Commit** `"Require dispute category and min-length evidence (vexatious guard)"`.

### Task 8: requestor abuse flag (derived helper + assignment payload)

**Files:**
- Modify: `app/modules/attestation/dispute_service.py` (add `requestor_rejected_dispute_count`)
- Modify: `app/modules/attestation/schemas.py` (`AttestorAssignmentResponse` gains `requestor_flagged: bool`)
- Modify: `app/modules/attestation/router.py` (`list_attestor_assignments` builder populates `requestor_flagged`) or `matching_service.list_attestor_assignments` if the flag is computed in the service
- Test: `tests/unit/modules/test_attestation_dispute_intake.py`

**Interfaces:**
- Produces: `async def requestor_rejected_dispute_count(db, *, requestor_id: UUID, now: datetime | None = None) -> int` — counts resolved disputes raised by `requestor_id` with outcome `rejected` and `resolved_at >= now - 365d`. Flag boolean = count ≥ `REQUESTOR_FLAG_THRESHOLD` (3).

> **Ordering note:** the `outcome == 'rejected'` column arrives in Slice 4. In Slice 3, implement the count against the *presence of a rejected resolution*, but since `outcome` does not yet exist, gate this helper's final predicate behind Slice 4. Concretely: ship the helper + threshold constant + `requestor_flagged` field now, computing against `status == 'resolved'` **and** the Slice-4 `outcome` column once it exists. To keep Slice 3 shippable and tested, count `status == 'resolved'` disputes in the window as a **provisional** signal, and add a Slice-4 Task-14 step that tightens the predicate to `outcome == 'rejected'`. Mark this clearly in the code with a `# TODO(module5-slice4)` comment referencing the tightening step.

- [ ] **Step 1: Failing test** — 2 rejected in window → not flagged; 3 → flagged; a 3rd resolved >12mo ago → not flagged.

```python
async def test_requestor_flag_threshold(db_session, frozen_now) -> None:
    """Three rejected disputes inside 12 months flags the requestor."""
    requestor = await _make_user("operator", "serial")
    await _seed_rejected_disputes(db_session, requestor_id=requestor.id, count=2,
                                  resolved_at=frozen_now)
    assert not await _flagged(db_session, requestor.id, frozen_now)
    await _seed_rejected_disputes(db_session, requestor_id=requestor.id, count=1,
                                  resolved_at=frozen_now)
    assert await _flagged(db_session, requestor.id, frozen_now)
```

- [ ] **Step 2: Run fail.**

- [ ] **Step 3: Implement helper** in `dispute_service.py`:

```python
from datetime import timedelta

REQUESTOR_FLAG_THRESHOLD = 3
REQUESTOR_FLAG_WINDOW_DAYS = 365


async def requestor_rejected_dispute_count(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    now: datetime | None = None,
) -> int:
    """Count a requestor's rejected disputes in the trailing 12 months.

    Rejected disputes (report stood against the requestor) are the abuse
    signal surfaced to attestors at match time. Derived, never stored.

    Maps to: Module 5 design spec section 4.5.
    """
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=REQUESTOR_FLAG_WINDOW_DAYS)
    count = await db.scalar(
        select(func.count())
        .select_from(AttestationDispute)
        .where(
            AttestationDispute.raised_by == requestor_id,
            AttestationDispute.status == "resolved",
            AttestationDispute.outcome == "rejected",  # Slice-4 column
            AttestationDispute.resolved_at.is_not(None),
            AttestationDispute.resolved_at >= cutoff,
        )
    )
    return int(count or 0)
```
Add `requestor_flagged: bool` to `AttestorAssignmentResponse` (default not allowed on a response model built explicitly — set it in the builder). Populate in `router.py` `list_attestor_assignments` by calling the helper per distinct requestor (batch: collect requestor ids, count once each) and comparing to `REQUESTOR_FLAG_THRESHOLD`.

> Because `outcome` is Slice 4, this task's helper will not import cleanly until Slice 4 adds the column. **Resolution:** implement Task 8 AFTER Task 14 within Slice 4 sequencing, OR ship Task 8's helper in Slice 3 using `status == 'resolved'` only, with the `outcome == 'rejected'` line added in Slice 4 Task 14. The plan's canonical order runs Slice 3 fully before Slice 4; therefore ship the Slice-3 helper with the `outcome` predicate **commented out** and a failing-safe `status == 'resolved'` count, then uncomment/tighten in Slice 4 Task 14. Keep the test asserting the threshold behavior (which holds under both predicates as long as the seed helper creates resolved disputes).

- [ ] **Step 4: Run tests + verify `requestor_flagged` present on the assignments endpoint (integration).**

- [ ] **Step 5: Commit** `"Add derived requestor abuse flag to attestor assignment payload"`.

---

## SLICE 4 — Resolution restructure (heavy)

### Task 9: outcome enum + revision_requested status + drop split (model + migration)

**Files:**
- Modify: `app/modules/attestation/models.py`
- Create: `migrations/versions/2026_07_01_0052_resolution_restructure.py`

**Interfaces:**
- Produces:
  - enum `attestation_dispute_outcome_enum` (`rejected`, `upheld_refund`, `upheld_revise`);
  - `AttestationDispute.outcome` (enum, nullable — set at resolution), `.is_complex` (bool default false), `.resolution_due_at` (timestamptz nullable), `.resolution_overdue_at` (timestamptz nullable);
  - `Attestation.revision_count` (int default 0), `.report_published_eligible` (bool default false);
  - status enum gains `revision_requested`;
  - **removed:** `AttestationDispute.resolution_type`, `.release_amount`, `.refund_amount`, and constraint `ck_attestation_disputes_split_has_amounts`; enum type `attestation_dispute_resolution_enum` dropped.

- [ ] **Step 1: Failing test** — assert new columns/enum exist and `resolution_type` is gone (a model-level test: `AttestationDispute.outcome` settable to `"upheld_revise"`; `hasattr(AttestationDispute, "resolution_type")` is False).

- [ ] **Step 2: Run fail.**

- [ ] **Step 3: Model edits** — add outcome enum; on `AttestationDispute` add `outcome`, `is_complex`, `resolution_due_at`, `resolution_overdue_at`; remove `resolution_type`, `release_amount`, `refund_amount`, and the split `CheckConstraint`. On `Attestation` add `revision_count` and `report_published_eligible`. Remove `ATTESTATION_DISPUTE_RESOLUTION_ENUM` definition.

- [ ] **Step 4: Migration** `2026_07_01_0052`, `down_revision="2026_07_01_0051"`:
  - `ALTER TYPE attestation_status_enum ADD VALUE IF NOT EXISTS 'revision_requested' AFTER 'report_submitted'` inside an `autocommit_block()` (mirror `0048`).
  - Create `attestation_dispute_outcome_enum`.
  - Add columns: `attestation_disputes.outcome` (nullable), `.is_complex` (not null default false), `.resolution_due_at`, `.resolution_overdue_at`; `attestations.revision_count` (not null default 0), `.report_published_eligible` (not null default false).
  - Drop constraint `ck_attestation_disputes_split_has_amounts`; drop columns `resolution_type`, `release_amount`, `refund_amount`.
  - `DROP TYPE IF EXISTS attestation_dispute_resolution_enum`.
  - **`downgrade`** recreates `attestation_dispute_resolution_enum`, re-adds the three dropped columns + constraint, drops the new columns/enum. (Note in the docstring: the `revision_requested` enum value cannot be removed on downgrade — Postgres limitation; leaving it is harmless. State this explicitly.)
  - **Human-review flag** in the migration docstring: this drops shipped columns.

- [ ] **Step 5: Run up/down/up + model test.**

- [ ] **Step 6: Commit** `"Restructure dispute resolution: outcome enum, drop split, add revision fields"`.

### Task 10: `resolve_dispute` — new outcome model (rejected / upheld_refund / upheld_revise)

**Files:**
- Modify: `app/modules/attestation/dispute_service.py` (`resolve_dispute` signature + body; remove `_validate_resolution_amounts` split logic)
- Modify: `app/modules/attestation/schemas.py` (`AdminAttestationDisputeResolveRequest`: replace `resolution_type`/amounts with `outcome`; `AttestationDisputeResponse`: replace `resolution_type`/amounts with `outcome`, `is_complex`, `resolution_due_at`)
- Modify: `app/modules/attestation/router.py` (`resolve_attestation_dispute` passes `outcome`)
- Modify: `app/modules/attestation/notifications.py` (`notify_dispute_resolved` takes `outcome`; add `notify_revision_requested`)
- Modify: `contracts/openapi.yaml`
- Test: `tests/unit/modules/test_attestation_resolution.py`

**Interfaces:**
- Consumes: `escrow_service.release`, `escrow_service.refund`, `stripe.create_refund`, `add_business_days`.
- Produces: `resolve_dispute(*, db, redis, admin, dispute_id, outcome: str, resolution_notes, totp_code) -> AttestationDispute`.

**Behavior per outcome:**
- `rejected` → `escrow_service.release(...admin_override=True)`; attestation → `closed`, `closed_at=now`, `report_published_eligible=True`; audit `attestation_released`.
- `upheld_refund` → Stripe refund (existing `_refund_escrow_to_stripe`) + `escrow_service.refund(...)`; attestation → `closed`, `closed_at=now`, `report_published_eligible=False`; write a **warning** (Task 13 helper); audit `attestation_refunded`.
- `upheld_revise` → escrow untouched (stays held); attestation → `revision_requested`, `revision_count += 1`; write a **warning**; audit `attestation_revision_requested`.

- [ ] **Step 1: Failing tests** — one per outcome:

```python
async def test_reject_releases_and_marks_publishable(db_session, redis, admin) -> None:
    dispute = await _open_dispute(db_session)  # attestation disputed, escrow held
    resolved = await dispute_service.resolve_dispute(
        db=db_session, redis=redis, admin=admin, dispute_id=dispute.id,
        outcome="rejected", resolution_notes="Report is sound; findings stand.",
        totp_code="000000",  # patched valid in fixtures
    )
    attestation = await db_session.get(Attestation, dispute.attestation_id)
    assert resolved.outcome == "rejected"
    assert attestation.status == "closed"
    assert attestation.report_published_eligible is True


async def test_upheld_refund_refunds_and_suppresses_publication(db_session, redis, admin) -> None:
    dispute = await _open_dispute(db_session, category="conflict_of_interest")
    resolved = await dispute_service.resolve_dispute(
        db=db_session, redis=redis, admin=admin, dispute_id=dispute.id,
        outcome="upheld_refund", resolution_notes="Undisclosed conflict confirmed.",
        totp_code="000000",
    )
    attestation = await db_session.get(Attestation, dispute.attestation_id)
    assert attestation.status == "closed"
    assert attestation.report_published_eligible is False


async def test_upheld_revise_reopens_for_resubmission(db_session, redis, admin) -> None:
    dispute = await _open_dispute(db_session, category="scope_error")
    await dispute_service.resolve_dispute(
        db=db_session, redis=redis, admin=admin, dispute_id=dispute.id,
        outcome="upheld_revise", resolution_notes="Wrong version reviewed; revise.",
        totp_code="000000",
    )
    attestation = await db_session.get(Attestation, dispute.attestation_id)
    assert attestation.status == "revision_requested"
    assert attestation.revision_count == 1
```

- [ ] **Step 2: Run fail.**

- [ ] **Step 3: Implement** — rewrite `resolve_dispute` around the `outcome` branch; delete `_validate_resolution_amounts` and split branch; `release_amount`/`refund_amount` no longer accepted. Set `dispute.outcome`, `dispute.resolved_at`, `dispute.admin_id`, `dispute.resolution_notes`, `dispute.status="resolved"`. Apply the per-outcome attestation transitions above. For `upheld_revise`, do NOT touch escrow; set `attestation.status="revision_requested"`, `attestation.revision_count += 1`. Call the warning helper (Task 13) for both upheld outcomes.

- [ ] **Step 4: Schemas + router + notifications + OpenAPI** — `AdminAttestationDisputeResolveRequest` becomes `{ outcome: Literal["rejected","upheld_refund","upheld_revise"], resolution_notes, totp_code }`. `AttestationDisputeResponse` drops `resolution_type`/amounts, adds `outcome`, `is_complex`, `resolution_due_at`. Router passes `outcome=payload.outcome`. `notify_dispute_resolved(attestation, *, outcome)`. Regenerate OpenAPI for the resolve endpoint + dispute response.

- [ ] **Step 5: Run resolution unit tests + existing dispute tests (updated for new fields).** Delete/replace old split tests.

- [ ] **Step 6: Commit** `"Rewrite dispute resolution around rejected/upheld_refund/upheld_revise outcomes"`.

### Task 11: revise-resubmit — reopen report submission from `revision_requested`

**Files:**
- Modify: `app/modules/attestation/report.py` (`submit_report` + `create_report_evidence_upload_session` allowed statuses)
- Test: `tests/unit/modules/test_attestation_submit.py`

**Interfaces:**
- Consumes: existing `submit_report`, quality gate, `add_business_days`.
- Produces: submit precondition accepts `{"in_review", "revision_requested"}`; resubmit re-runs the quality gate, regenerates the PDF, sets a fresh dispute window, and applies the revision SLA late-flag.

- [ ] **Step 1: Failing test:**

```python
async def test_resubmit_from_revision_requested_reruns_gate_and_reopens_window(
    db_session, frozen_monday
) -> None:
    """A revised report re-enters report_submitted with a fresh dispute window.

    Enforces Module 5 spec section 4.6 (revise-resubmit loop).
    """
    attestation = await _revision_requested_quality_attestation(db_session)
    result = await report.submit_report(
        db=db_session, attestor=attestation.attestor_user,
        attestation_id=attestation.id,
        payload=_valid_submit_payload(outcome="approved"),
    )
    assert result.status == "report_submitted"
    assert result.dispute_window_ends_at == datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
```

- [ ] **Step 2: Run fail** — precondition rejects `revision_requested` (409).

- [ ] **Step 3: Implement** — locate `_load_assigned_attestation_for_update(..., allowed_statuses={"in_review"})` calls in `submit_report` and `create_report_evidence_upload_session`; widen to `{"in_review", "revision_requested"}`. The rest of `submit_report` (gate, window via `add_business_days`, PDF dispatch) already runs unchanged. Confirm the revision SLA / late-flag: on resubmit, `completion_due_at` for the revision equals `add_business_days(review_start_or_now, attestation_revision_sla_business_days)` — set this when `resolve_dispute` transitions to `revision_requested` (add to Task 10's `upheld_revise` branch: `attestation.completion_due_at = add_business_days(now, revision_sla)`), so the existing late-flag logic in `submit_report` fires correctly. Add config helper for `attestation_revision_sla_business_days` (default 5).

> Adjust Task 10's `upheld_revise` branch to set `completion_due_at` via the revision SLA. This is the one cross-task coupling; the interface is: `upheld_revise` sets `completion_due_at = add_business_days(now, revision_sla)`.

- [ ] **Step 4: Run submit tests (old + new).**

- [ ] **Step 5: Commit** `"Allow report resubmission from revision_requested with fresh window"`.

### Task 12: `report_published_eligible` stamp on accept / auto-accept

**Files:**
- Modify: `app/modules/attestation/release_service.py` (`_release_and_close` sets `report_published_eligible=True`)
- Test: `tests/unit/modules/test_attestation_release.py` (existing) or `test_attestation_resolution.py`

**Interfaces:**
- Produces: every release-and-close path stamps `report_published_eligible=True`.

- [ ] **Step 1: Failing test** — after `accept_report` and after `auto_release_attestations`, `attestation.report_published_eligible is True`.

- [ ] **Step 2: Run fail** (default False).

- [ ] **Step 3: Implement** — in `_release_and_close`, add `attestation.report_published_eligible = True` alongside `attestation.status = "closed"`.

- [ ] **Step 4: Tighten `rating_service._report_stood`** — replace the Slice-2 predicate with the explicit flag:

```python
def _report_stood(attestation: Attestation) -> bool:
    """Return whether the report stood (Module 5 section 4.9)."""
    return bool(attestation.report_published_eligible)
```
Update the Slice-2 rating tests' `_closed_after_accept` / `_closed_after_refund` helpers to set/leave `report_published_eligible` accordingly.

- [ ] **Step 5: Run rating + release tests.**

- [ ] **Step 6: Commit** `"Stamp report_published_eligible on release and gate rating on it"`.

---

## SLICE 5 — Warnings + suspension-review + resolution-SLA clock

### Task 13: `AttestorWarning` table + warning-on-upheld + derived suspension trigger

**Files:**
- Modify: `app/modules/attestation/models.py` (add `AttestorWarning`; add `AttestorProfile.suspension_review_at`)
- Create: `migrations/versions/2026_07_01_0053_attestor_warnings.py`
- Modify: `app/modules/attestation/dispute_service.py` (add `_write_warning`, `attestor_upheld_warning_count`, suspension-trigger check; call from both upheld branches in `resolve_dispute`)
- Modify: `app/modules/attestation/notifications.py` (`notify_attestor_warning`, `notify_suspension_review`)
- Test: `tests/unit/modules/test_attestation_warnings.py`

**Interfaces:**
- Produces:
  - `AttestorWarning` — table `attestor_warnings` (`id`, `attestor_id` fk users, `dispute_id` fk `attestation_disputes.id` nullable, `reason` text, `created_at`);
  - `AttestorProfile.suspension_review_at` (timestamptz nullable);
  - `async def attestor_upheld_warning_count(db, *, attestor_id, now=None) -> int` (trailing 12 months);
  - suspension trigger: count ≥ `SUSPENSION_REVIEW_THRESHOLD` (2) → set `suspension_review_at`, audit, notify admin. Never deactivates.

- [ ] **Step 1: Failing tests:**

```python
async def test_upheld_dispute_writes_warning(db_session, redis, admin) -> None:
    """Every upheld dispute records a formal attestor warning."""
    dispute = await _open_dispute(db_session, category="scope_error")
    attestor_id = (await db_session.get(Attestation, dispute.attestation_id)).attestor_id
    await dispute_service.resolve_dispute(
        db=db_session, redis=redis, admin=admin, dispute_id=dispute.id,
        outcome="upheld_revise", resolution_notes="Revise scope.", totp_code="000000",
    )
    count = await db_session.scalar(
        select(func.count()).select_from(AttestorWarning).where(
            AttestorWarning.attestor_id == attestor_id
        )
    )
    assert count == 1


async def test_second_upheld_in_window_flags_suspension_review(db_session, redis, admin) -> None:
    """A second upheld dispute within 12 months flips suspension review."""
    attestor = await _make_attestor(db_session)
    await _resolve_upheld(db_session, redis, admin, attestor, outcome="upheld_revise")
    await _resolve_upheld(db_session, redis, admin, attestor, outcome="upheld_refund")
    profile = await _profile(db_session, attestor.id)
    assert profile.suspension_review_at is not None
```

- [ ] **Step 2: Run fail.**

- [ ] **Step 3: Model + migration** — add `AttestorWarning` model; add `suspension_review_at` to `AttestorProfile`. Migration `2026_07_01_0053`, `down_revision="2026_07_01_0052"`: `create_table("attestor_warnings", ...)`, `add_column("attestor_profiles", "suspension_review_at")`. Downgrade drops both.

- [ ] **Step 4: Service** — in `dispute_service.py`:

```python
SUSPENSION_REVIEW_THRESHOLD = 2
SUSPENSION_REVIEW_WINDOW_DAYS = 365


async def _write_warning(
    db: AsyncSession, *, attestor_id: UUID, dispute_id: UUID, reason: str, now: datetime
) -> None:
    """Record one formal attestor warning and flag suspension review if due."""
    db.add(
        AttestorWarning(
            attestor_id=attestor_id, dispute_id=dispute_id, reason=reason
        )
    )
    await db.flush()
    count = await attestor_upheld_warning_count(db, attestor_id=attestor_id, now=now)
    if count >= SUSPENSION_REVIEW_THRESHOLD:
        profile = await db.scalar(
            select(AttestorProfile)
            .where(AttestorProfile.user_id == attestor_id)
            .with_for_update()
        )
        if profile is not None and profile.suspension_review_at is None:
            profile.suspension_review_at = now
            await write_audit(
                db=db, actor_id=None, action="attestor_suspension_review_flagged",
                target_type="attestor_profile", target_id=profile.id,
                metadata={"upheld_warnings": count},
            )


async def attestor_upheld_warning_count(
    db: AsyncSession, *, attestor_id: UUID, now: datetime | None = None
) -> int:
    """Count an attestor's formal warnings in the trailing 12 months."""
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=SUSPENSION_REVIEW_WINDOW_DAYS)
    count = await db.scalar(
        select(func.count()).select_from(AttestorWarning).where(
            AttestorWarning.attestor_id == attestor_id,
            AttestorWarning.created_at >= cutoff,
        )
    )
    return int(count or 0)
```
Call `_write_warning(...)` inside `resolve_dispute` for `upheld_refund` and `upheld_revise` (attestation.attestor_id is the subject). Notify admin + attestor. Import `AttestorWarning`, `AttestorProfile`.

- [ ] **Step 5: Run warning tests + resolution tests.**

- [ ] **Step 6: Commit** `"Add attestor warnings and derived suspension-review trigger"`.

### Task 14: resolution SLA clock (`resolution_due_at`) at dispute creation + `is_complex`

**Files:**
- Modify: `app/modules/attestation/dispute_service.py` (`create_dispute` sets `resolution_due_at`; `resolve_dispute`/an admin toggle sets `is_complex`)
- Modify: `app/modules/attestation/schemas.py` (`AdminAttestationDisputeResolveRequest` gains `is_complex: bool = False`; or a dedicated toggle)
- Test: `tests/unit/modules/test_attestation_resolution.py`

**Interfaces:**
- Produces: `create_dispute` stamps `resolution_due_at = add_business_days(now, 5)`; setting `is_complex` recomputes `resolution_due_at = add_business_days(created_at, 15)`.

- [ ] **Step 1: Failing test** — new dispute has `resolution_due_at == add_business_days(created_at, 5)`; marking complex extends to 15.

- [ ] **Step 2: Run fail.**

- [ ] **Step 3: Implement** — in `create_dispute`, set `dispute.resolution_due_at = add_business_days(current_time, RESOLUTION_SLA_STANDARD_BUSINESS_DAYS)` (constant 5). Add `RESOLUTION_SLA_COMPLEX_BUSINESS_DAYS = 15`. Allow `is_complex` to be set via the resolve request (or a small admin patch) and recompute `resolution_due_at` from `created_at` when toggled true. Also **tighten Task 8's `requestor_rejected_dispute_count`** now that `outcome` exists: uncomment the `AttestationDispute.outcome == "rejected"` predicate.

- [ ] **Step 4: Run resolution + requestor-flag tests (now with the tightened predicate).**

- [ ] **Step 5: Commit** `"Add resolution SLA due date and is_complex extension"`.

### Task 15: retune escalate beat → flag overdue resolutions

**Files:**
- Modify: `app/modules/attestation/dispute_service.py` (`escalate_attestation_disputes` → flag overdue)
- Modify: `app/workers/tasks/attestation_beat.py` (result key rename optional)
- Test: `tests/unit/workers/test_attestation_beat.py` (or the dispute-service unit test for the sweep)

**Interfaces:**
- Produces: `escalate_attestation_disputes(db, *, now=None) -> int` now flags disputes past `resolution_due_at` — sets `resolution_overdue_at`, writes audit `attestation_dispute_resolution_overdue`, notifies admin. Still bumps `open` → `under_review` on first pickup. NO auto-resolve, NO escrow movement.

- [ ] **Step 1: Failing test:**

```python
async def test_overdue_resolution_is_flagged_not_resolved(db_session, frozen_now) -> None:
    """A dispute past its resolution_due_at is flagged overdue, never auto-resolved.

    Enforces Module 5 spec section 4.8 (money stays human).
    """
    dispute = await _open_dispute_due_in_past(db_session, now=frozen_now)
    flagged = await dispute_service.escalate_attestation_disputes(
        db=db_session, now=frozen_now
    )
    refreshed = await db_session.get(AttestationDispute, dispute.id)
    assert flagged == 1
    assert refreshed.resolution_overdue_at is not None
    assert refreshed.status != "resolved"  # never auto-resolved
```

- [ ] **Step 2: Run fail.**

- [ ] **Step 3: Implement** — rewrite `escalate_attestation_disputes` to select active disputes (`status in ('open','under_review')`) with `resolution_due_at <= now` and `resolution_overdue_at IS NULL`; set `resolution_overdue_at = now`, move `open`→`under_review`, audit, notify admin. Return the count flagged. Keep the beat wrapper name; optionally rename the result key to `overdue_count`.

- [ ] **Step 4: Run beat/sweep tests + confirm `auto_release_attestations` still respects fresh windows and open disputes (existing tests green).**

- [ ] **Step 5: Commit** `"Retune dispute escalation beat to flag overdue resolutions"`.

---

## Final verification (after all slices)

- [ ] `uv run pytest tests/ -k "attestation and not migration"` — full attestation suite green.
- [ ] Migration-only tests isolated: `uv run pytest tests/ -k "migration" -p no:randomly` green.
- [ ] `uv run alembic upgrade head && uv run alembic downgrade -4 && uv run alembic upgrade head` — the five M5 migrations round-trip.
- [ ] Whole-repo gate: `uv run ruff check .` and `uv run mypy app` — clean.
- [ ] `contracts/openapi.yaml` parses and matches `app.openapi()` for every changed path (rating, dispute create, dispute resolve, assignments payload).
- [ ] Coverage ≥ 80% on `app/modules/attestation/**` and `app/workers/**`.
- [ ] Spec §5.1–5.5 each maps to a shipped task (coverage table below).

### Spec coverage map

| Spec § | Requirement | Task(s) |
|---|---|---|
| 4.1 | business-day util | 1 |
| 4.2 / 4.9 window | 5-bd window + config rename | 2 |
| 4.3 | rating table + endpoint + eligibility | 3, 4, 5, 12 |
| 4.4 | category enum + evidence guard | 6, 7 |
| 4.5 | derived requestor flag | 8, 14 |
| 4.6 | outcome enum, drop split, revise-resubmit | 9, 10, 11 |
| 4.7 | warnings + suspension review | 13 |
| 4.8 | resolution SLA clock + beat retune | 14, 15 |
| 4.9 | publication eligibility stamp | 9, 12 |
| 4.6 no-re-dispute | state machine + revision_count | 9, 11 |
