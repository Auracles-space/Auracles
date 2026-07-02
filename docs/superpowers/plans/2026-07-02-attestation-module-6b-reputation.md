# Attestation Module 6b — Reputation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Attestor a reputation subject — M5 star ratings drive a 0-100 score via the existing reputation engine, that score feeds AMM matching, and a merit threshold awards sticky "Certified Attestor" status.

**Architecture:** Reuse the existing reputation engine (`combine_factors` → `reputation_scores` → daily recompute Beat). Add `attestor` as a 4th subject type with a new two-factor aggregator (rating + reliability). Certification is a sticky server-side write on `AttestorProfile.certified_attestor_at`, evaluated inside the recompute transaction. AMM matching swaps its hardcoded neutral reputation for the attestor's real score. All backend; no new endpoint, no money movement.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, PostgreSQL 16, Celery, loguru, pytest/pytest-asyncio, `uv`.

## Global Constraints

- All commands run from `backend/`. Test runner: `uv run pytest <path> -v`.
- Whole-repo checks before claiming clean: `uv run ruff check .` and `uv run mypy app` (both from `backend/`).
- Config values follow the "code default, no seed migration" pattern (6a): read from `platform_config`, in-code default, runtime-overridable.
- `verification_level` is onboarding vetting — **never** overwritten by 6b. Merit L5 lives in the new `certified_attestor_at` column.
- Certification is **sticky**: set once, never cleared by recompute.
- AMM cold-start: an unscored or provisional attestor contributes neutral `0.5` reputation.
- "Stood attestation" = `Attestation.status == "closed"` AND `report_published_eligible == True`.
- Attestor factor weights: `{"rating": "0.75", "reliability": "0.25"}` (must sum to 1). `reputation_min_activity_attestor` = `3`. `attestor_reliability_penalty` = `0.10`. `attestor_certification_min_attestations` = `10`. `attestor_certification_min_avg_rating` = `4.5`.
- Escrow / money / audit are sensitive: this module touches none of the escrow or payout paths. The migration alters a CHECK constraint and adds a nullable column only — additive, no column drop.
- No `Co-Authored-By` trailer on commits. Work on `main`.
- Head migration before this plan: `2026_07_01_0053`.

---

### Task 1: Migration + model field — attestor as reputation subject

**Files:**
- Create: `migrations/versions/2026_07_02_0054_attestor_reputation_subject.py`
- Modify: `app/modules/attestation/models.py` (`AttestorProfile`, after `suspension_review_at` ~line 388)
- Test: `tests/unit/modules/test_attestor_reputation_subject_migration.py`

**Interfaces:**
- Produces: `reputation_scores` CHECK `ck_reputation_subject_type` now allows `'attestor'`; `attestor_profiles.certified_attestor_at` (nullable `TIMESTAMPTZ`); `AttestorProfile.certified_attestor_at: Mapped[datetime | None]`.

- [ ] **Step 1: Write the failing test**

```python
"""Migration coverage for Module 6b: attestor as a reputation subject.

Verifies the CHECK constraint on reputation_scores admits 'attestor' and the
new certified_attestor_at column exists after upgrade to head.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.modules.attestation.models import AttestorProfile


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Upgrade to head and yield a sync engine for schema assertions."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield engine
    finally:
        engine.dispose()


def test_certified_attestor_at_column_exists(migrated_engine: Engine) -> None:
    """attestor_profiles gains a nullable certified_attestor_at column."""
    columns = {
        col["name"]: col
        for col in inspect(migrated_engine).get_columns("attestor_profiles")
    }
    assert "certified_attestor_at" in columns
    assert columns["certified_attestor_at"]["nullable"] is True


def test_reputation_scores_accepts_attestor_subject(migrated_engine: Engine) -> None:
    """The subject-type CHECK constraint admits an 'attestor' row."""
    row_id = uuid4()
    subject_id = uuid4()
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reputation_scores "
                "(id, subject_type, subject_id, components, is_provisional) "
                "VALUES (:id, 'attestor', :sid, '{}'::jsonb, true)"
            ),
            {"id": row_id, "sid": subject_id},
        )
        conn.execute(text("DELETE FROM reputation_scores WHERE id = :id"), {"id": row_id})


def test_model_exposes_certified_attestor_at() -> None:
    """AttestorProfile ORM model maps certified_attestor_at."""
    assert "certified_attestor_at" in AttestorProfile.__table__.columns.keys()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/modules/test_attestor_reputation_subject_migration.py -v`
Expected: FAIL — `certified_attestor_at` not in columns / INSERT violates check constraint / model attribute missing.

- [ ] **Step 3: Write the migration**

Create `migrations/versions/2026_07_02_0054_attestor_reputation_subject.py`:

```python
"""Add attestor as a reputation subject.

Module 6b: the Attestor becomes a reputation subject. Widen the
reputation_scores subject-type CHECK to admit 'attestor', and add the sticky
merit flag attestor_profiles.certified_attestor_at (Auracles Certified
Attestor / Verification Level 5), kept distinct from onboarding
verification_level.

Maps to: Module 6b design spec sections 4.1, 7.

Revision ID: 2026_07_02_0054
Revises: 2026_07_01_0053
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_02_0054"
down_revision: str | Sequence[str] | None = "2026_07_01_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_CHECK = (
    "subject_type IN ('framework','contributor','operator','attestor')"
)
_OLD_CHECK = "subject_type IN ('framework','contributor','operator')"


def upgrade() -> None:
    """Widen the subject-type CHECK and add certified_attestor_at."""
    op.drop_constraint(
        "ck_reputation_subject_type", "reputation_scores", type_="check"
    )
    op.create_check_constraint(
        "ck_reputation_subject_type", "reputation_scores", _NEW_CHECK
    )
    op.add_column(
        "attestor_profiles",
        sa.Column("certified_attestor_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove certified_attestor_at and narrow the subject-type CHECK.

    Any 'attestor' reputation_scores rows are removed first so the narrowed
    constraint can be recreated.
    """
    op.drop_column("attestor_profiles", "certified_attestor_at")
    op.execute("DELETE FROM reputation_scores WHERE subject_type = 'attestor'")
    op.drop_constraint(
        "ck_reputation_subject_type", "reputation_scores", type_="check"
    )
    op.create_check_constraint(
        "ck_reputation_subject_type", "reputation_scores", _OLD_CHECK
    )
```

- [ ] **Step 4: Add the model field**

In `app/modules/attestation/models.py`, inside `AttestorProfile`, immediately after the `suspension_review_at` column (~line 391), add:

```python
    certified_attestor_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
```

(`datetime`, `DateTime`, `Mapped`, `mapped_column` are already imported in this file.)

- [ ] **Step 5: Run migration up/down + tests**

Run:
```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run pytest tests/unit/modules/test_attestor_reputation_subject_migration.py -v
```
Expected: all migration commands succeed; all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add migrations/versions/2026_07_02_0054_attestor_reputation_subject.py \
  app/modules/attestation/models.py \
  tests/unit/modules/test_attestor_reputation_subject_migration.py
git commit -m "Add attestor as reputation subject: CHECK + certified_attestor_at"
```

---

### Task 2: Attestor reputation config (weights + certification thresholds)

**Files:**
- Modify: `app/modules/reputation/weights.py`
- Test: `tests/unit/modules/test_reputation_weights.py` (append)

**Interfaces:**
- Consumes: `ReputationConfig` dataclass, `load_config(db, *, subject_type)`.
- Produces: `ReputationConfig` gains `reliability_penalty: Decimal`, `cert_min_attestations: int`, `cert_min_avg_rating: Decimal` (all with defaults). `load_config(db, subject_type="attestor")` returns weights `{rating: 0.75, reliability: 0.25}`, `min_activity=3`, `reliability_penalty=0.10`, `cert_min_attestations=10`, `cert_min_avg_rating=4.5` absent overrides.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/modules/test_reputation_weights.py`:

```python
async def test_attestor_config_defaults(db_session) -> None:
    """Attestor config loads default weights, activity floor, and cert thresholds."""
    from decimal import Decimal

    from app.modules.reputation.weights import load_config

    cfg = await load_config(db_session, subject_type="attestor")
    assert cfg.weights == {
        "rating": Decimal("0.75"),
        "reliability": Decimal("0.25"),
    }
    assert cfg.min_activity == 3
    assert cfg.reliability_penalty == Decimal("0.10")
    assert cfg.cert_min_attestations == 10
    assert cfg.cert_min_avg_rating == Decimal("4.5")
```

> Note: this file's existing tests already use a `db_session` fixture. If the file has no such fixture, mirror the `db_session`/`migrated_database` fixtures from `tests/unit/modules/test_reputation_factors.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/modules/test_reputation_weights.py::test_attestor_config_defaults -v`
Expected: FAIL — `KeyError: 'attestor'` in `_DEFAULT_WEIGHTS`.

- [ ] **Step 3: Implement config**

In `app/modules/reputation/weights.py`:

Add an `attestor` entry to `_DEFAULT_WEIGHTS`:

```python
    "attestor": {
        "rating": "0.75",
        "reliability": "0.25",
    },
```

Add `attestor` to `_DEFAULT_MIN_ACTIVITY`:

```python
_DEFAULT_MIN_ACTIVITY = {
    "framework": 3,
    "contributor": 1,
    "operator": 1,
    "attestor": 3,
}
```

Append three fields (with defaults) to the `ReputationConfig` dataclass, after `dispute_penalty`:

```python
    reliability_penalty: Decimal = Decimal("0.10")
    cert_min_attestations: int = 10
    cert_min_avg_rating: Decimal = Decimal("4.5")
```

In `load_config`, after `dispute_penalty` is read and before the validation block, add:

```python
    reliability_penalty = Decimal(
        await _raw(db, "attestor_reliability_penalty") or "0.10"
    )
    cert_min_attestations = int(
        await _raw(db, "attestor_certification_min_attestations") or "10"
    )
    cert_min_avg_rating = Decimal(
        await _raw(db, "attestor_certification_min_avg_rating") or "4.5"
    )
```

Extend the validation block to cover the new values (add to the existing checks):

```python
    if (
        reliability_penalty < 0
        or reliability_penalty > 1
        or cert_min_attestations < 1
        or cert_min_avg_rating < 1
        or cert_min_avg_rating > 5
    ):
        raise ValueError(
            "attestor reliability_penalty must be 0-1, cert_min_attestations >= 1, "
            "and cert_min_avg_rating 1-5"
        )
```

Pass the new fields into the `ReputationConfig(...)` constructor at the end:

```python
    return ReputationConfig(
        subject_type=subject_type,
        weights=weights_map,
        min_activity=min_activity,
        prior=prior,
        prior_strength_k=prior_strength_k,
        decay_halflife_days=decay_halflife_days,
        dispute_penalty=dispute_penalty,
        reliability_penalty=reliability_penalty,
        cert_min_attestations=cert_min_attestations,
        cert_min_avg_rating=cert_min_avg_rating,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/modules/test_reputation_weights.py -v`
Expected: PASS (new test + all existing weight tests still green).

- [ ] **Step 5: Commit**

```bash
git add app/modules/reputation/weights.py tests/unit/modules/test_reputation_weights.py
git commit -m "Add attestor reputation config: weights + certification thresholds"
```

---

### Task 3: `attestor_factors` aggregator (rating + reliability)

**Files:**
- Modify: `app/modules/reputation/factors.py`
- Test: `tests/unit/modules/test_reputation_attestor_factors.py`

**Interfaces:**
- Consumes: `FactorResult`, `ReputationConfig` (with `reliability_penalty`), `_avg_review_norm`, `AttestationRating`, `AttestorProfile`, `AttestorWarning`, `Attestation`.
- Produces: `async def attestor_factors(db: AsyncSession, user_id: UUID, cfg: ReputationConfig) -> dict[str, FactorResult]` returning keys `{"rating", "reliability"}`. Signature matches the `_FACTOR_FN` contract `fn(db, subject_id, cfg)`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/modules/test_reputation_attestor_factors.py`:

```python
"""DB-backed factor aggregator test for the attestor subject type.

Builds attestor profile, stood attestations, ratings, and warnings inline,
then checks the rating average and reliability-penalty factors.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
    AttestorProfile,
    AttestorWarning,
)
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework
from app.modules.reputation import factors
from app.modules.reputation.weights import load_config
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure source tables exist before the test runs."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean(migrated_database) -> AsyncIterator[None]:
    """Reset attestor-factor rows in FK-safe order around each test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as s:
            await s.execute(delete(AuditLog))
            await s.execute(delete(AttestationRating))
            await s.execute(delete(AttestorWarning))
            await s.execute(delete(Attestation))
            await s.execute(delete(AttestorProfile))
            await s.execute(delete(Framework))
            await s.execute(delete(UserRole))
            await s.execute(delete(User))
            await s.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _seed_attestor(
    *, ratings: list[int], warnings: int, late: int
) -> UUID:
    """Create an attestor with stood attestations, ratings, and warnings."""
    async with async_session_factory() as s:
        async with s.begin():
            attestor = User(
                email=f"att-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Att",
                is_active=True,
            )
            requestor = User(
                email=f"req-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Req",
                is_active=True,
            )
            s.add_all([attestor, requestor])
            await s.flush()
            s.add(
                AttestorProfile(
                    user_id=attestor.id,
                    specializations=["ml"],
                    jurisdictions=["us"],
                    late_submission_count=late,
                )
            )
            for stars in ratings:
                att = Attestation(
                    requestor_id=requestor.id,
                    attestor_id=attestor.id,
                    target_type="contributor",
                    target_id=requestor.id,
                    review_type="quality",
                    status="closed",
                    report_published_eligible=True,
                    fee_amount=Decimal("300.00"),
                    currency="USD",
                )
                s.add(att)
                await s.flush()
                s.add(
                    AttestationRating(
                        attestation_id=att.id, rated_by=requestor.id, stars=stars
                    )
                )
            for _ in range(warnings):
                s.add(
                    AttestorWarning(
                        attestor_id=attestor.id, reason="upheld dispute"
                    )
                )
            return attestor.id


async def test_rating_factor_is_normalized_average() -> None:
    """rating = (avg_stars - 1)/4 with evidence = number of ratings."""
    attestor_id = await _seed_attestor(ratings=[5, 5, 4], warnings=0, late=0)
    async with async_session_factory() as db:
        cfg = await load_config(db, subject_type="attestor")
        result = await factors.attestor_factors(db, attestor_id, cfg)
    # avg = 14/3 = 4.6667 -> (4.6667-1)/4 = 0.9167
    assert result["rating"].evidence == 3
    assert result["rating"].value == pytest.approx(Decimal("0.9167"), abs=Decimal("0.001"))
    # no penalties -> reliability 1.0, evidence = stood count (3)
    assert result["reliability"].value == Decimal("1")
    assert result["reliability"].evidence == 3


async def test_reliability_penalty_from_warnings_and_late() -> None:
    """reliability = max(0, 1 - 0.10*(warnings + late_submission_count))."""
    attestor_id = await _seed_attestor(ratings=[4, 4], warnings=2, late=1)
    async with async_session_factory() as db:
        cfg = await load_config(db, subject_type="attestor")
        result = await factors.attestor_factors(db, attestor_id, cfg)
    # 0.10 * (2 warnings + 1 late) = 0.30 -> reliability 0.70
    assert result["reliability"].value == Decimal("0.70")


async def test_no_ratings_scores_zero_without_error() -> None:
    """An attestor with no ratings gets rating value 0, evidence 0 (no divide-by-zero)."""
    attestor_id = await _seed_attestor(ratings=[], warnings=0, late=0)
    async with async_session_factory() as db:
        cfg = await load_config(db, subject_type="attestor")
        result = await factors.attestor_factors(db, attestor_id, cfg)
    assert result["rating"].value == Decimal("0")
    assert result["rating"].evidence == 0
```

> If `Attestation` requires columns beyond those set here (e.g. a non-null field with no server default), read `app/modules/attestation/models.py` `class Attestation` and add the minimal required fields to the inline builder.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/modules/test_reputation_attestor_factors.py -v`
Expected: FAIL — `AttributeError: module 'factors' has no attribute 'attestor_factors'`.

- [ ] **Step 3: Implement the aggregator**

In `app/modules/reputation/factors.py`:

Extend the top-of-file model import (currently `from app.modules.attestation.models import Attestation`) to:

```python
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
    AttestorProfile,
    AttestorWarning,
)
```

Append the aggregator (after `operator_factors`):

```python
async def attestor_factors(
    db: AsyncSession,
    user_id: UUID,
    cfg: ReputationConfig,
) -> dict[str, FactorResult]:
    """Aggregate reputation factors for one attestor.

    The rating factor is the normalized average of requestor star ratings on
    the attestor's stood attestations. The reliability factor penalizes upheld
    warnings and late submissions, floored at zero, with evidence equal to the
    attestor's stood-attestation count.
    """
    stood_ids = (
        select(Attestation.id)
        .where(
            Attestation.attestor_id == user_id,
            Attestation.status == "closed",
            Attestation.report_published_eligible.is_(True),
        )
        .scalar_subquery()
    )

    avg_stars, rating_count = (
        await db.execute(
            select(
                func.avg(AttestationRating.stars),
                func.count(AttestationRating.id),
            ).where(AttestationRating.attestation_id.in_(stood_ids))
        )
    ).one()
    rating = FactorResult(
        _avg_review_norm(Decimal(str(avg_stars)) if avg_stars is not None else None),
        int(rating_count or 0),
    )

    stood_count = int(
        await db.scalar(
            select(func.count()).select_from(
                select(Attestation.id)
                .where(
                    Attestation.attestor_id == user_id,
                    Attestation.status == "closed",
                    Attestation.report_published_eligible.is_(True),
                )
                .subquery()
            )
        )
        or 0
    )
    warning_count = int(
        await db.scalar(
            select(func.count(AttestorWarning.id)).where(
                AttestorWarning.attestor_id == user_id
            )
        )
        or 0
    )
    late_count = int(
        await db.scalar(
            select(AttestorProfile.late_submission_count).where(
                AttestorProfile.user_id == user_id
            )
        )
        or 0
    )
    penalty = cfg.reliability_penalty * Decimal(warning_count + late_count)
    reliability = FactorResult(max(Decimal("0"), Decimal("1") - penalty), stood_count)

    return {"rating": rating, "reliability": reliability}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/modules/test_reputation_attestor_factors.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/reputation/factors.py tests/unit/modules/test_reputation_attestor_factors.py
git commit -m "Add attestor_factors: rating average + reliability penalty"
```

---

### Task 4: Wire attestor into reputation service + recompute enumeration

**Files:**
- Modify: `app/modules/reputation/service.py` (`VALID_SUBJECT_TYPES` ~line 25, `subject_exists` ~line 156, `_public_subject_exists` ~line 181)
- Modify: `app/workers/tasks/reputation.py` (`_FACTOR_FN` ~line 27, `_recompute_all_impl` ~line 54)
- Test: `tests/integration/test_reputation_attestor_recompute.py`

**Interfaces:**
- Consumes: `factors.attestor_factors` (Task 3), `AttestorProfile`, `combine_factors`, `upsert_score`.
- Produces: `read_reputation(subject_type="attestor", ...)` returns a payload for an existing attestor profile and `None` otherwise; `recompute_subject(subject_type="attestor", subject_id=<uuid>)` computes and upserts an attestor score; `recompute_reputation()` return dict gains an `"attestor"` count key.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_reputation_attestor_recompute.py`:

```python
"""Integration: attestor reputation recompute + read path."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.reputation import service as reputation_service
from app.workers.tasks import reputation as reputation_tasks

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean(migrated_database) -> AsyncIterator[None]:
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        from app.modules.reputation.models import ReputationScore
        from app.shared.models.audit_log import AuditLog

        async with async_session_factory() as s:
            await s.execute(delete(AuditLog))
            await s.execute(delete(ReputationScore))
            await s.execute(delete(AttestationRating))
            await s.execute(delete(Attestation))
            await s.execute(delete(AttestorProfile))
            await s.execute(delete(UserRole))
            await s.execute(delete(User))
            await s.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _seed(*, stars: list[int]) -> UUID:
    async with async_session_factory() as s:
        async with s.begin():
            attestor = User(
                email=f"a-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="A",
                is_active=True,
            )
            requestor = User(
                email=f"r-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="R",
                is_active=True,
            )
            s.add_all([attestor, requestor])
            await s.flush()
            s.add(
                AttestorProfile(
                    user_id=attestor.id,
                    specializations=["ml"],
                    jurisdictions=["us"],
                )
            )
            for st in stars:
                att = Attestation(
                    requestor_id=requestor.id,
                    attestor_id=attestor.id,
                    target_type="contributor",
                    target_id=requestor.id,
                    review_type="quality",
                    status="closed",
                    report_published_eligible=True,
                    fee_amount=Decimal("300.00"),
                    currency="USD",
                )
                s.add(att)
                await s.flush()
                s.add(
                    AttestationRating(
                        attestation_id=att.id, rated_by=requestor.id, stars=st
                    )
                )
            return attestor.id


async def test_recompute_subject_scores_attestor(clean) -> None:
    """recompute_subject stores a non-provisional attestor score for enough ratings."""
    del clean
    attestor_id = await _seed(stars=[5, 5, 5, 4])
    await reputation_tasks.recompute_subject(
        subject_type="attestor", subject_id=attestor_id
    )
    async with async_session_factory() as db:
        score = await reputation_service.get_score(
            db, subject_type="attestor", subject_id=attestor_id
        )
    assert score is not None
    assert score.is_provisional is False
    assert score.score > Decimal("80")


async def test_read_reputation_returns_attestor_payload(clean) -> None:
    """read_reputation resolves an existing attestor and 404s a non-attestor."""
    del clean
    attestor_id = await _seed(stars=[5, 5, 5, 4])
    await reputation_tasks.recompute_subject(
        subject_type="attestor", subject_id=attestor_id
    )
    async with async_session_factory() as db:
        payload = await reputation_service.read_reputation(
            db, subject_type="attestor", subject_id=attestor_id
        )
        missing = await reputation_service.read_reputation(
            db, subject_type="attestor", subject_id=uuid4()
        )
    assert payload is not None
    assert payload["subject_type"] == "attestor"
    assert missing is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_reputation_attestor_recompute.py -v`
Expected: FAIL — `KeyError: 'attestor'` in `_FACTOR_FN`, or `read_reputation` returns `None` because `subject_exists` treats attestor as operator.

- [ ] **Step 3: Wire the service**

In `app/modules/reputation/service.py`:

Change `VALID_SUBJECT_TYPES`:

```python
VALID_SUBJECT_TYPES = ("framework", "contributor", "operator", "attestor")
```

In `subject_exists`, add an attestor branch **before** the `role = ...` fallback line:

```python
    if subject_type == "attestor":
        from app.modules.attestation.models import AttestorProfile

        return await db.scalar(
            select(AttestorProfile.id).where(AttestorProfile.user_id == subject_id)
        ) is not None
    role = "contributor" if subject_type == "contributor" else "operator"
```

In `_public_subject_exists`, add an attestor branch **before** the final `return await subject_exists(...)`:

```python
    if subject_type == "attestor":
        from app.modules.attestation.models import AttestorProfile

        return await db.scalar(
            select(AttestorProfile.id).where(
                AttestorProfile.user_id == subject_id,
                AttestorProfile.active.is_(True),
            )
        ) is not None
```

- [ ] **Step 4: Wire recompute enumeration**

In `app/workers/tasks/reputation.py`:

Add `attestor` to `_FACTOR_FN`:

```python
_FACTOR_FN = {
    "framework": factors.framework_factors,
    "contributor": factors.contributor_factors,
    "operator": factors.operator_factors,
    "attestor": factors.attestor_factors,
}
```

In `_recompute_all_impl`, add the import and enumeration. Update the import line to also bring in `AttestorProfile`:

```python
    from app.modules.attestation.models import AttestorProfile
    from app.modules.auth.models import UserRole
```

Change the counts initializer:

```python
    counts = {"framework": 0, "contributor": 0, "operator": 0, "attestor": 0}
```

Inside the `async with async_session_factory() as db:` block, after the `operator_ids` query, add:

```python
        attestor_ids = (
            (
                await db.execute(
                    select(AttestorProfile.user_id).where(
                        AttestorProfile.active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
```

After the operator recompute loop, add:

```python
    for aid in set(attestor_ids):
        await recompute_subject(subject_type="attestor", subject_id=aid)
        counts["attestor"] += 1
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_reputation_attestor_recompute.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add app/modules/reputation/service.py app/workers/tasks/reputation.py \
  tests/integration/test_reputation_attestor_recompute.py
git commit -m "Wire attestor into reputation service + daily recompute sweep"
```

---

### Task 5: Sticky Certified Attestor evaluation

**Files:**
- Create: `app/modules/attestation/certification_service.py`
- Modify: `app/workers/tasks/reputation.py` (`recompute_subject` ~line 34)
- Test: `tests/unit/modules/test_attestor_certification.py`

**Interfaces:**
- Consumes: `ReputationConfig` (`cert_min_attestations`, `cert_min_avg_rating`), `AttestorProfile`, `Attestation`, `AttestationRating`, `write_audit`.
- Produces: `async def evaluate_attestor_certification(db: AsyncSession, *, attestor_id: UUID, cfg: ReputationConfig) -> bool` — sets `certified_attestor_at` + writes `attestor_certified` audit when newly eligible; returns whether it certified on this call. Called from `recompute_subject` inside the recompute transaction for the attestor branch.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/modules/test_attestor_certification.py`:

```python
"""Unit tests for sticky Certified Attestor evaluation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation.certification_service import (
    evaluate_attestor_certification,
)
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.reputation.weights import load_config
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean(migrated_database) -> AsyncIterator[None]:
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as s:
            await s.execute(delete(AuditLog))
            await s.execute(delete(AttestationRating))
            await s.execute(delete(Attestation))
            await s.execute(delete(AttestorProfile))
            await s.execute(delete(UserRole))
            await s.execute(delete(User))
            await s.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _seed(*, stood: int, stars: int) -> UUID:
    """Create an attestor with `stood` stood attestations each rated `stars`."""
    async with async_session_factory() as s:
        async with s.begin():
            attestor = User(
                email=f"a-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="A",
                is_active=True,
            )
            requestor = User(
                email=f"r-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="R",
                is_active=True,
            )
            s.add_all([attestor, requestor])
            await s.flush()
            s.add(
                AttestorProfile(
                    user_id=attestor.id,
                    specializations=["ml"],
                    jurisdictions=["us"],
                )
            )
            for _ in range(stood):
                att = Attestation(
                    requestor_id=requestor.id,
                    attestor_id=attestor.id,
                    target_type="contributor",
                    target_id=requestor.id,
                    review_type="quality",
                    status="closed",
                    report_published_eligible=True,
                    fee_amount=Decimal("300.00"),
                    currency="USD",
                )
                s.add(att)
                await s.flush()
                s.add(
                    AttestationRating(
                        attestation_id=att.id, rated_by=requestor.id, stars=stars
                    )
                )
            return attestor.id


async def _run(attestor_id: UUID) -> bool:
    async with async_session_factory() as db:
        cfg = await load_config(db, subject_type="attestor")
        async with db.begin():
            result = await evaluate_attestor_certification(
                db, attestor_id=attestor_id, cfg=cfg
            )
    return result


async def _certified_at(attestor_id: UUID) -> datetime | None:
    async with async_session_factory() as db:
        return await db.scalar(
            select(AttestorProfile.certified_attestor_at).where(
                AttestorProfile.user_id == attestor_id
            )
        )


async def test_certifies_when_thresholds_met(clean) -> None:
    """10+ stood attestations averaging >= 4.5 certifies the attestor."""
    del clean
    attestor_id = await _seed(stood=10, stars=5)
    assert await _run(attestor_id) is True
    assert await _certified_at(attestor_id) is not None
    async with async_session_factory() as db:
        audits = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "attestor_certified")
            )
        ).scalars().all()
    assert len(audits) == 1


async def test_below_count_threshold_does_not_certify(clean) -> None:
    """Nine stood attestations is below the default threshold of 10."""
    del clean
    attestor_id = await _seed(stood=9, stars=5)
    assert await _run(attestor_id) is False
    assert await _certified_at(attestor_id) is None


async def test_already_certified_is_sticky_and_not_reaudited(clean) -> None:
    """A certified attestor stays certified and is never re-stamped or re-audited."""
    del clean
    attestor_id = await _seed(stood=10, stars=5)
    assert await _run(attestor_id) is True
    first = await _certified_at(attestor_id)
    # second run must be a no-op
    assert await _run(attestor_id) is False
    assert await _certified_at(attestor_id) == first
    async with async_session_factory() as db:
        count = len(
            (
                await db.execute(
                    select(AuditLog).where(AuditLog.action == "attestor_certified")
                )
            ).scalars().all()
        )
    assert count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/modules/test_attestor_certification.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.attestation.certification_service`.

- [ ] **Step 3: Implement the certification service**

Create `app/modules/attestation/certification_service.py`:

```python
"""Sticky Certified Attestor (Verification Level 5) evaluation.

Module 6b section 4.3: when an attestor reaches the merit threshold — a
minimum number of stood attestations at or above a minimum average rating —
they are awarded Auracles Certified Attestor status. The award is sticky: set
once via ``certified_attestor_at`` and never cleared by recompute. A lapse in
standing is handled by the suspension-review / admin path, not by silent
decertification.

Maps to: Module 6b design spec section 4.3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
    AttestorProfile,
)
from app.modules.reputation.weights import ReputationConfig


async def evaluate_attestor_certification(
    db: AsyncSession,
    *,
    attestor_id: UUID,
    cfg: ReputationConfig,
) -> bool:
    """Award Certified Attestor status when merit thresholds are first met.

    Runs inside the caller's transaction. Locks the profile row, and does
    nothing if the attestor is already certified (sticky) or below either
    threshold.

    Args:
        db: Async session (must be inside an open transaction).
        attestor_id: The attestor's user id.
        cfg: Loaded attestor reputation config supplying the thresholds.

    Returns:
        True if this call newly certified the attestor, else False.
    """
    profile = await db.scalar(
        select(AttestorProfile)
        .where(AttestorProfile.user_id == attestor_id)
        .with_for_update()
    )
    if profile is None or profile.certified_attestor_at is not None:
        return False

    stood_ids = (
        select(Attestation.id)
        .where(
            Attestation.attestor_id == attestor_id,
            Attestation.status == "closed",
            Attestation.report_published_eligible.is_(True),
        )
        .scalar_subquery()
    )
    stood_count = int(
        await db.scalar(
            select(func.count()).select_from(
                select(Attestation.id)
                .where(
                    Attestation.attestor_id == attestor_id,
                    Attestation.status == "closed",
                    Attestation.report_published_eligible.is_(True),
                )
                .subquery()
            )
        )
        or 0
    )
    if stood_count < cfg.cert_min_attestations:
        return False

    avg_stars = await db.scalar(
        select(func.avg(AttestationRating.stars)).where(
            AttestationRating.attestation_id.in_(stood_ids)
        )
    )
    if avg_stars is None or Decimal(str(avg_stars)) < cfg.cert_min_avg_rating:
        return False

    profile.certified_attestor_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=None,
        action="attestor_certified",
        target_type="attestor",
        target_id=attestor_id,
        metadata={"stood_count": stood_count, "avg_rating": str(avg_stars)},
    )
    logger.bind(
        module="attestation",
        action="attestor_certified",
        user_id=attestor_id,
    ).info("attestor_certified", stood_count=stood_count)
    return True
```

- [ ] **Step 4: Call it from recompute_subject**

In `app/workers/tasks/reputation.py`, in `recompute_subject`, inside the `async with db.begin():` block, after the `upsert_score(...)` call, add:

```python
            if subject_type == "attestor":
                from app.modules.attestation.certification_service import (
                    evaluate_attestor_certification,
                )

                await evaluate_attestor_certification(
                    db, attestor_id=subject_id, cfg=cfg
                )
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
uv run pytest tests/unit/modules/test_attestor_certification.py -v
uv run pytest tests/integration/test_reputation_attestor_recompute.py -v
```
Expected: certification tests PASS; recompute tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/attestation/certification_service.py app/workers/tasks/reputation.py \
  tests/unit/modules/test_attestor_certification.py
git commit -m "Add sticky Certified Attestor evaluation to recompute"
```

---

### Task 6: Targeted recompute on rating submission

**Files:**
- Modify: `app/modules/attestation/rating_service.py` (`submit_rating`, after the commit block ~line 115)
- Test: `tests/integration/test_attestation_rating.py` (append; create if absent)

**Interfaces:**
- Consumes: `recompute_subject_task` (Celery task, `app.workers.tasks.reputation`), `Attestation.attestor_id`.
- Produces: `submit_rating` enqueues `recompute_subject_task.delay("attestor", str(attestor_id))` after the rating commit when the attestation has an attestor.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_attestation_rating.py` (create the file with the same fixtures used by other integration rating tests if it does not exist — mirror `tests/integration/test_reputation_attestor_recompute.py` fixtures; the assertion below is what matters):

```python
async def test_submit_rating_enqueues_attestor_recompute(clean, monkeypatch) -> None:
    """Submitting a rating enqueues a targeted attestor reputation recompute."""
    del clean
    calls: list[tuple] = []

    def _capture(*args):
        calls.append(args)

    from app.workers.tasks import reputation as reputation_tasks

    monkeypatch.setattr(reputation_tasks.recompute_subject_task, "delay", _capture)

    attestor_id, requestor, attestation_id = await _seed_rateable_attestation()
    async with async_session_factory() as db:
        await rating_service.submit_rating(
            db=db,
            requestor=requestor,
            attestation_id=attestation_id,
            stars=5,
            comment=None,
        )
    assert ("attestor", str(attestor_id)) in calls
```

> `_seed_rateable_attestation()` must create an attestor + requestor + a stood (`status="closed"`, `report_published_eligible=True`) attestation with `attestor_id` set, and return `(attestor_id, requestor_user, attestation_id)`. Reuse the seeding shape from `tests/integration/test_reputation_attestor_recompute.py`. Import `from app.modules.attestation import rating_service`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_attestation_rating.py::test_submit_rating_enqueues_attestor_recompute -v`
Expected: FAIL — `calls` is empty (no enqueue yet).

- [ ] **Step 3: Implement the enqueue**

In `app/modules/attestation/rating_service.py`, in `submit_rating`, replace the tail (from `log.info("attestation_rated")` to `return rating`) with:

```python
    log.info("attestation_rated")
    if attestation.attestor_id is not None:
        from app.workers.tasks.reputation import recompute_subject_task

        recompute_subject_task.delay("attestor", str(attestation.attestor_id))
    return rating
```

(The `attestation` object was loaded inside the transaction; `attestor_id` is available after commit. The enqueue is deliberately after the commit so a broker outage cannot roll back the rating.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_attestation_rating.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/attestation/rating_service.py tests/integration/test_attestation_rating.py
git commit -m "Enqueue targeted attestor recompute on rating submission"
```

---

### Task 7: AMM cold-start — feed real attestor reputation into matching

**Files:**
- Modify: `app/modules/attestation/scoring.py` (`reputation_score` ~line 92)
- Modify: `app/modules/attestation/matching_service.py` (`_rank_eligible_attestors` ~line 839)
- Test: `tests/unit/modules/test_attestation_scoring.py` (append) + `tests/unit/modules/test_attestation_matching_ranking.py` (append)

**Interfaces:**
- Consumes: `ReputationScore` (`subject_type`, `subject_id`, `score`, `is_provisional`).
- Produces: `scoring.reputation_score(normalized: float = 0.5) -> float` returns `normalized`; `_rank_eligible_attestors` passes each candidate's `score/100` (non-provisional) or `0.5` (unscored/provisional) into `scoring.reputation_score`.

- [ ] **Step 1: Write the failing scoring test**

Append to `tests/unit/modules/test_attestation_scoring.py`:

```python
def test_reputation_score_returns_normalized_value() -> None:
    """reputation_score echoes the supplied normalized value; defaults to 0.5."""
    from app.modules.attestation import scoring

    assert scoring.reputation_score(0.8) == 0.8
    assert scoring.reputation_score() == 0.5
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/modules/test_attestation_scoring.py::test_reputation_score_returns_normalized_value -v`
Expected: FAIL — `reputation_score() takes 0 positional arguments but 1 was given`.

- [ ] **Step 3: Implement the scoring param**

In `app/modules/attestation/scoring.py`, replace `reputation_score`:

```python
def reputation_score(normalized: float = 0.5) -> float:
    """Return the attestor's normalized reputation, or the neutral swap point.

    Args:
        normalized: The attestor's reputation in [0.0, 1.0]. Defaults to the
            neutral 0.5 swap point for unscored or provisional attestors so a
            new attestor is neither rewarded nor penalized.

    Returns:
        The normalized reputation value.
    """
    return normalized
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/modules/test_attestation_scoring.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing ranking test**

Append to `tests/unit/modules/test_attestation_matching_ranking.py` a test that seeds two eligible attestors, stores a non-provisional `ReputationScore` of `90.00` for one, and asserts the higher-reputation attestor ranks first when all other factors tie. Use the file's existing `db_session` fixture and helpers (`_make_user`, whatever profile/attestation seeders the file provides). Skeleton:

```python
async def test_ranking_uses_stored_attestor_reputation(db_session) -> None:
    """A higher stored reputation lifts an otherwise-tied attestor above its peer."""
    from decimal import Decimal

    from app.modules.attestation import matching_service
    from app.modules.reputation.models import ReputationScore

    # Two attestors with identical specializations/jurisdictions/categories so
    # sector/category/availability tie; only reputation differs.
    high = await _make_eligible_attestor(spec=["ml"], juris=["us"])
    low = await _make_eligible_attestor(spec=["ml"], juris=["us"])
    attestation = await _make_matching_attestation(spec=["ml"], juris=["us"])

    async with async_session_factory() as s:
        async with s.begin():
            s.add(
                ReputationScore(
                    subject_type="attestor",
                    subject_id=high,
                    score=Decimal("90.00"),
                    components={},
                    is_provisional=False,
                )
            )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=set(),
        limit=5,
        now=datetime.now(UTC),
    )
    ids = [c.user_id for c in ranked]
    assert ids.index(high) < ids.index(low)
    high_candidate = next(c for c in ranked if c.user_id == high)
    assert high_candidate.breakdown["reputation"] == 0.9
```

> Build `_make_eligible_attestor` / `_make_matching_attestation` from the seeding already present in this test file (it constructs `AttestorProfile` + `Attestation` rows for the existing ranking tests). Ensure both attestors clear the CoI/expiry/cap gates so only reputation differs.

- [ ] **Step 6: Run to verify it fails**

Run: `uv run pytest tests/unit/modules/test_attestation_matching_ranking.py::test_ranking_uses_stored_attestor_reputation -v`
Expected: FAIL — both candidates get `reputation == 0.5`, so the order is decided by the FIFO tiebreak, not reputation.

- [ ] **Step 7: Implement the matching batch-load**

In `app/modules/attestation/matching_service.py`, in `_rank_eligible_attestors`, after `profiles = list((await db.execute(query)).scalars().all())` and its empty guard, before `owner_id = ...`, add:

```python
    from app.modules.reputation.models import ReputationScore

    reputation_rows = await db.execute(
        select(
            ReputationScore.subject_id,
            ReputationScore.score,
            ReputationScore.is_provisional,
        ).where(
            ReputationScore.subject_type == "attestor",
            ReputationScore.subject_id.in_([p.user_id for p in profiles]),
        )
    )
    reputation_by_user = {
        subject_id: (score, is_provisional)
        for subject_id, score, is_provisional in reputation_rows.all()
    }
```

In the per-profile scoring loop, replace `"reputation": scoring.reputation_score(),` with:

```python
        rep = reputation_by_user.get(profile.user_id)
        if rep is not None and rep[1] is False and rep[0] is not None:
            rep_norm = float(rep[0]) / 100.0
        else:
            rep_norm = 0.5
        factors = {
            "sector": scoring.sector_alignment(
                attestation.requested_specializations,
                profile.sectors,
                profile.specializations,
            ),
            "category": scoring.category_match(
                framework_category,
                profile.framework_categories,
            ),
            "credential": scoring.credential_relevance(),
            "availability": scoring.availability_score(active_count, concurrency_cap),
            "reputation": scoring.reputation_score(rep_norm),
        }
```

(This replaces the existing `factors = {...}` block; keep the surrounding `if _is_coi_conflicted`, `active_count`, and cap-check lines unchanged.)

- [ ] **Step 8: Run tests to verify they pass**

Run:
```bash
uv run pytest tests/unit/modules/test_attestation_matching_ranking.py -v
uv run pytest tests/unit/modules/test_attestation_scoring.py -v
```
Expected: PASS (new tests + all existing ranking tests still green).

- [ ] **Step 9: Commit**

```bash
git add app/modules/attestation/scoring.py app/modules/attestation/matching_service.py \
  tests/unit/modules/test_attestation_scoring.py \
  tests/unit/modules/test_attestation_matching_ranking.py
git commit -m "Feed real attestor reputation into AMM matching (cold-start neutral)"
```

---

### Task 8: Directory read exposure (reputation score + certified flag)

**Files:**
- Modify: `app/modules/attestation/schemas.py` (`AttestorDirectoryEntry` ~line 719)
- Modify: `app/modules/attestation/directory_service.py` (`_directory_entry` ~line 90)
- Test: `tests/integration/test_attestor_directory.py` (append; create if absent using this file's fixtures)

**Interfaces:**
- Consumes: `reputation_service.get_score`, `AttestorProfile.certified_attestor_at`.
- Produces: `AttestorDirectoryEntry` gains `certified: bool`; `reputation` is populated with the attestor's non-provisional score (as `float`) or `None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_attestor_directory.py` (mirror the file's existing directory-seeding fixtures; if the file does not exist, create it seeding an active `AttestorProfile` + a non-provisional `ReputationScore` + `certified_attestor_at` set):

```python
async def test_directory_entry_exposes_reputation_and_certified(clean) -> None:
    """A certified, scored attestor exposes a float reputation and certified=True."""
    del clean
    from decimal import Decimal

    from app.modules.attestation import directory_service
    from app.modules.reputation.models import ReputationScore

    attestor_id = await _seed_active_attestor()  # active AttestorProfile + user
    async with async_session_factory() as s:
        async with s.begin():
            profile = await s.scalar(
                select(AttestorProfile).where(AttestorProfile.user_id == attestor_id)
            )
            profile.certified_attestor_at = datetime.now(UTC)
            s.add(
                ReputationScore(
                    subject_type="attestor",
                    subject_id=attestor_id,
                    score=Decimal("88.00"),
                    components={},
                    is_provisional=False,
                )
            )

    async with async_session_factory() as db:
        entry = await directory_service.get_directory_profile(db, attestor_id)
    assert entry.certified is True
    assert entry.reputation == 88.0


async def test_directory_entry_hides_provisional_reputation(clean) -> None:
    """A provisional (or unscored) attestor exposes reputation None, certified False."""
    del clean
    from app.modules.attestation import directory_service

    attestor_id = await _seed_active_attestor()
    async with async_session_factory() as db:
        entry = await directory_service.get_directory_profile(db, attestor_id)
    assert entry.certified is False
    assert entry.reputation is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_attestor_directory.py -v`
Expected: FAIL — `AttestorDirectoryEntry` has no `certified` field / `reputation` is always `None`.

- [ ] **Step 3: Add the schema field**

In `app/modules/attestation/schemas.py`, in `AttestorDirectoryEntry`, after `reputation: float | None`:

```python
    certified: bool = False
```

- [ ] **Step 4: Populate in the directory service**

In `app/modules/attestation/directory_service.py`:

Add the import near the top:

```python
from app.modules.reputation import service as reputation_service
```

Replace the `_directory_entry` return with:

```python
async def _directory_entry(
    *,
    db: AsyncSession,
    user_id: UUID,
    display_name: str,
    profile: AttestorProfile,
) -> AttestorDirectoryEntry:
    """Build one public Attestor directory entry."""
    score = await reputation_service.get_score(
        db, subject_type="attestor", subject_id=user_id
    )
    reputation = (
        float(score.score)
        if score is not None
        and score.is_provisional is False
        and score.score is not None
        else None
    )
    return AttestorDirectoryEntry(
        user_id=user_id,
        display_name=display_name,
        sectors=profile.sectors,
        framework_categories=profile.framework_categories,
        jurisdictions=profile.jurisdictions,
        verification_level=profile.verification_level,
        credentials=await _verified_credentials(db=db, user_id=user_id),
        completed_attestations=await _completed_attestations(db=db, user_id=user_id),
        reputation=reputation,
        certified=profile.certified_attestor_at is not None,
    )
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/integration/test_attestor_directory.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add app/modules/attestation/schemas.py app/modules/attestation/directory_service.py \
  tests/integration/test_attestor_directory.py
git commit -m "Expose attestor reputation score + certified flag in directory"
```

---

## Final verification

- [ ] **Whole-repo lint + type check**

Run (from `backend/`):
```bash
uv run ruff check .
uv run mypy app
```
Expected: clean. Fix any findings in the touched files.

- [ ] **Full migration round-trip**

Run:
```bash
uv run alembic upgrade head
uv run alembic downgrade 2026_07_01_0053
uv run alembic upgrade head
```
Expected: all succeed.

- [ ] **Full 6b test pass**

Run:
```bash
uv run pytest \
  tests/unit/modules/test_attestor_reputation_subject_migration.py \
  tests/unit/modules/test_reputation_weights.py \
  tests/unit/modules/test_reputation_attestor_factors.py \
  tests/unit/modules/test_attestor_certification.py \
  tests/unit/modules/test_attestation_scoring.py \
  tests/unit/modules/test_attestation_matching_ranking.py \
  tests/integration/test_reputation_attestor_recompute.py \
  tests/integration/test_attestation_rating.py \
  tests/integration/test_attestor_directory.py -v
```
Expected: all PASS.

## Reviewer notes (cross-cutting)

- **No escrow/money path touched.** 6b reads ratings/warnings and writes a reputation score + a sticky merit flag. Confirm no diff reaches `financials/` or escrow logic.
- **Certification stickiness.** Task 5's `certified_attestor_at IS NOT NULL` guard is the only thing preventing re-award/re-audit under the double trigger (rating-submit + daily). Verify no other code path clears `certified_attestor_at`.
- **AMM regression.** Existing ranking tests assumed `reputation == 0.5` for all. After Task 7 they must still pass because unscored attestors still resolve to `0.5`. If any existing ranking test now seeds a score, that is a plan-conflict — flag it.
- **`ReputationConfig` positional constructors.** Task 2 appends fields with defaults; the positional `_cfg(...)` helper in `test_reputation_engine.py` must still construct successfully. Verify that test file stays green.
