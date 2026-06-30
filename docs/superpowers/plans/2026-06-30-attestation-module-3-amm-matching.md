# Attestation Module 3 — AMM Matching Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the FIFO Attestor-selection stub with the spec'd weighted AMM score, add CoI conflict + availability screening, and add the annual CoI re-sign enforcement + reminder layer.

**Architecture:** Surgical. `offer_next_cohort` already builds the `excluded_ids` set and creates cohort offer rows; only the candidate-selection helper changes — from `_matching_attestor_ids` (FIFO) to `_rank_eligible_attestors` (scored). A new pure `scoring.py` holds the formula. A daily Celery Beat task sends CoI-expiry reminders; expiry enforcement is folded into the matching SQL filter. One Alembic migration adds three nullable columns.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, Pydantic v2, PostgreSQL 16, Celery + Beat, pytest + pytest-asyncio, loguru. Package manager: `uv` (run tests with `uv run pytest`, lint with `uv run ruff check .`, types with `uv run mypy app`). All backend commands run from `backend/`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-30-attestation-module-3-amm-matching-design.md` — source of truth; source workflow `docs/Auracles Attestation — Product Development Workflow.md` §3.1–§3.4.
- **Weights (verbatim):** `Sector 0.30 + Category 0.25 + Credential 0.20 + Availability 0.15 + Reputation 0.10` (sum = 1.0).
- **Swap-point constants:** `CREDENTIAL_RELEVANCE_BASELINE = 0.5`, `REPUTATION_BASELINE = 0.5`.
- **Availability cap:** `_platform_int_config(db, key="attestation_concurrency_cap", default=5, minimum=1)`. Active-assignment statuses = `{"accepted", "report_submitted", "disputed"}`. `offered` does NOT count.
- **CoI enforcement:** eligible only if `coi_signed_at IS NOT NULL AND coi_expires_at > now`.
- **CoI conflict:** exclude if any `coi_declarations[]` entry's `subject_id` ∈ `{target_id, owner_id, requestor_id}`. Malformed entry → skipped, WARNING logged, never excludes.
- **Tie-break (verbatim order):** score DESC → `approved_at` ASC → `user_id`.
- **Category source:** `AttestorProfile.framework_categories` (dedicated array — exists). Sector source: `AttestorProfile.sectors ∪ specializations`.
- **TDD:** failing test first, every task. Backend coverage ≥ 80% on `app/modules/**` and `app/workers/**`.
- **Logging:** `loguru` only, never `print`/stdlib logging. Bind `module="attestation"` + snake_case `action`. No PII / no secrets / no brief contents in logs or audit metadata — IDs, counts, numbers, bools only.
- **Docstrings:** module + every public function (Google style). Migration docstring states the WHY + maps to the spec.
- **Migrations:** new Alembic file, `down_revision = "2026_06_30_0046"`; both `alembic upgrade head` and `alembic downgrade -1` must succeed; nullable columns, no backfill.
- **Commits:** end at the last meaningful line — NO `Co-Authored-By` / generated trailer. Work on `main` (current branch); do not branch.
- **Whole-repo gates before claiming clean:** `uv run ruff check .` and `uv run mypy app` (CI lints tests too).

---

## File Structure

- **Create** `backend/app/modules/attestation/scoring.py` — pure scoring: weights, swap-point constants, per-factor functions, `compute_match_score`. No DB, no I/O.
- **Create** `backend/migrations/versions/2026_06_30_0047_amm_matching_scores.py` — adds `attestation_offers.match_score`, `attestation_offers.score_breakdown`, `attestor_profiles.coi_reminder_sent_at`.
- **Modify** `backend/app/modules/attestation/models.py` — add the three columns to the ORM models.
- **Modify** `backend/app/modules/attestation/schemas.py` — extend `CoiEntry` with optional `subject_id` / `subject_kind`.
- **Modify** `backend/app/modules/attestation/matching_service.py` — replace `_matching_attestor_ids` with `_rank_eligible_attestors`; wire scores into `offer_next_cohort`; add `send_coi_resign_reminders`.
- **Modify** `backend/app/modules/attestation/notifications.py` — add `notify_coi_expiring` + `notify_coi_lapsed` (user-targeted, not Attestation-targeted).
- **Modify** `backend/app/workers/tasks/attestation_beat.py` — add the `send_coi_resign_reminders` Celery wrapper.
- **Modify** `backend/app/workers/beat_schedule.py` — add the daily schedule entry.
- **Test** `backend/tests/unit/modules/test_attestation_scoring.py` (new) — per-factor + weighted-sum unit tests.
- **Test** `backend/tests/unit/modules/test_attestation_matching_ranking.py` (new) — eligibility/screening/ranking unit tests.
- **Test** `backend/tests/unit/workers/test_attestation_coi_reminder.py` (new) — reminder-window + dedup tests.
- **Test** `backend/tests/integration/test_attestation_offers.py` (extend if exists, else create) — score persisted on offers.

---

### Task 1: Migration + model columns

**Files:**
- Modify: `backend/app/modules/attestation/models.py` (`AttestationOffer` ~`models.py:560`, `AttestorProfile` ~`models.py:345`)
- Create: `backend/migrations/versions/2026_06_30_0047_amm_matching_scores.py`

**Interfaces:**
- Produces: `AttestationOffer.match_score: Mapped[Decimal | None]`, `AttestationOffer.score_breakdown: Mapped[dict | None]`, `AttestorProfile.coi_reminder_sent_at: Mapped[datetime | None]`. All nullable.

- [ ] **Step 1: Add the columns to the ORM models**

In `models.py`, inside `class AttestationOffer`, after the `expires_at` column add:

```python
    match_score: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 3),
        nullable=True,
    )
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
```

Inside `class AttestorProfile`, after the `coi_expires_at` column add:

```python
    coi_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
```

Confirm `Numeric`, `JSONB`, `Decimal`, `Any` are already imported at the top of `models.py` (they are — `Numeric` from sqlalchemy, `JSONB` from `sqlalchemy.dialects.postgresql`, `Decimal` from `decimal`, `Any` from `typing`). If any is missing, add it.

- [ ] **Step 2: Create the migration**

```python
"""Add AMM match-score columns and CoI reminder timestamp.

Supports Attestation Module 3 (AMM Matching Engine). Persists the computed
match score + factor breakdown on each cohort offer for auditability ("why was
this Attestor picked?"), and a CoI re-sign reminder timestamp on the Attestor
profile to dedupe the daily expiry-reminder Beat task.

Maps to: spec 2026-06-30-attestation-module-3-amm-matching-design.md §5, §7.

Revision ID: 2026_06_30_0047
Revises: 2026_06_30_0046
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "2026_06_30_0047"
down_revision = "2026_06_30_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attestation_offers",
        sa.Column("match_score", sa.Numeric(4, 3), nullable=True),
    )
    op.add_column(
        "attestation_offers",
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "coi_reminder_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("attestor_profiles", "coi_reminder_sent_at")
    op.drop_column("attestation_offers", "score_breakdown")
    op.drop_column("attestation_offers", "match_score")
```

- [ ] **Step 3: Run the migration up and down**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed, no errors.

- [ ] **Step 4: Lint + types**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/attestation/models.py backend/migrations/versions/2026_06_30_0047_amm_matching_scores.py
git commit -m "feat(attestation): add AMM match-score + CoI reminder columns"
```

---

### Task 2: Scoring module (`scoring.py`)

**Files:**
- Create: `backend/app/modules/attestation/scoring.py`
- Test: `backend/tests/unit/modules/test_attestation_scoring.py`

**Interfaces:**
- Produces:
  - `WEIGHTS: dict[str, float]`
  - `CREDENTIAL_RELEVANCE_BASELINE: float` (= 0.5), `REPUTATION_BASELINE: float` (= 0.5)
  - `sector_alignment(requested: list[str], profile_sectors: list[str], profile_specializations: list[str]) -> float`
  - `category_match(framework_category: str | None, profile_framework_categories: list[str]) -> float`
  - `availability_score(active_count: int, cap: int) -> float`
  - `credential_relevance() -> float`
  - `reputation_score() -> float`
  - `compute_match_score(factors: dict[str, float]) -> tuple[float, dict[str, float]]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/modules/test_attestation_scoring.py`:

```python
"""Unit tests for the AMM scoring formula and per-factor functions.

Verifies each factor maps inputs to [0,1] per the spec, including the
neutral-on-missing-constraint rules, and that compute_match_score applies the
locked weights.

Maps to: spec §1 (Components) AMM Scoring.
"""

from __future__ import annotations

import pytest

from app.modules.attestation import scoring


def test_weights_sum_to_one():
    assert pytest.approx(sum(scoring.WEIGHTS.values()), abs=1e-9) == 1.0


def test_swap_point_constants_are_neutral():
    assert scoring.CREDENTIAL_RELEVANCE_BASELINE == 0.5
    assert scoring.REPUTATION_BASELINE == 0.5


def test_sector_alignment_full_overlap():
    assert scoring.sector_alignment(["tax", "audit"], ["tax"], ["audit"]) == 1.0


def test_sector_alignment_partial():
    assert scoring.sector_alignment(["tax", "audit"], ["tax"], []) == 0.5


def test_sector_alignment_no_overlap():
    assert scoring.sector_alignment(["tax"], ["legal"], ["hr"]) == 0.0


def test_sector_alignment_empty_request_is_neutral():
    assert scoring.sector_alignment([], ["tax"], []) == 1.0


def test_category_match_in_set():
    assert scoring.category_match("compliance", ["compliance", "tax"]) == 1.0


def test_category_match_not_in_set():
    assert scoring.category_match("compliance", ["tax"]) == 0.0


def test_category_match_none_is_neutral():
    assert scoring.category_match(None, []) == 1.0


def test_availability_no_active_is_full():
    assert scoring.availability_score(0, 5) == 1.0


def test_availability_partial():
    assert scoring.availability_score(4, 5) == pytest.approx(0.2)


def test_availability_floor_at_zero():
    assert scoring.availability_score(5, 5) == 0.0


def test_compute_match_score_weights_and_breakdown():
    factors = {
        "sector": 1.0,
        "category": 1.0,
        "credential": 0.5,
        "availability": 1.0,
        "reputation": 0.5,
    }
    score, breakdown = scoring.compute_match_score(factors)
    # 0.30 + 0.25 + 0.10 + 0.15 + 0.05 = 0.85
    assert score == 0.85
    assert breakdown == factors
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestation_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.attestation.scoring'`.

- [ ] **Step 3: Implement `scoring.py`**

Create `backend/app/modules/attestation/scoring.py`:

```python
"""Pure AMM scoring for Attestation matching (§3.2).

Holds the locked weighted formula and per-factor functions. No DB or I/O —
every factor is a deterministic function of plain inputs so each is unit-tested
in isolation. Two factors have no data source yet and resolve to a neutral
0.5 baseline: Credential Relevance (needs credential tagging) and Reputation
(Module 6 §6.4). Each is a single swap-point when its data lands.

Maps to: spec 2026-06-30-attestation-module-3-amm-matching-design.md.
"""

from __future__ import annotations

WEIGHTS: dict[str, float] = {
    "sector": 0.30,
    "category": 0.25,
    "credential": 0.20,
    "availability": 0.15,
    "reputation": 0.10,
}

# Swap-points: replace with real computations when the data exists.
CREDENTIAL_RELEVANCE_BASELINE = 0.5
REPUTATION_BASELINE = 0.5


def sector_alignment(
    requested: list[str],
    profile_sectors: list[str],
    profile_specializations: list[str],
) -> float:
    """Fraction of requested specializations covered by the Attestor's scope.

    An unconstrained request (empty ``requested``) is neutral (1.0) — it must
    not penalize any candidate.

    Args:
        requested: The request's requested specializations.
        profile_sectors: The Attestor profile's declared sectors.
        profile_specializations: The Attestor profile's specializations.

    Returns:
        ``|requested ∩ (sectors ∪ specializations)| / |requested|`` in [0,1];
        1.0 when ``requested`` is empty.
    """
    if not requested:
        return 1.0
    covered = set(profile_sectors) | set(profile_specializations)
    matched = sum(1 for item in requested if item in covered)
    return matched / len(requested)


def category_match(
    framework_category: str | None,
    profile_framework_categories: list[str],
) -> float:
    """Whether the target framework's category is in the Attestor's categories.

    Non-framework targets (``framework_category is None``) are neutral (1.0):
    the factor does not apply and must not penalize.

    Args:
        framework_category: The target framework category, or None for
            non-framework targets.
        profile_framework_categories: The Attestor's declared framework
            categories.

    Returns:
        1.0 if matched or not applicable, else 0.0.
    """
    if framework_category is None:
        return 1.0
    return 1.0 if framework_category in set(profile_framework_categories) else 0.0


def availability_score(active_count: int, cap: int) -> float:
    """Linear availability from active-assignment load.

    Args:
        active_count: Count of the Attestor's active assignments.
        cap: Configured concurrency cap (>= 1).

    Returns:
        ``max(0, (cap - active_count) / cap)`` in [0,1].
    """
    if cap <= 0:
        return 0.0
    return max(0.0, (cap - active_count) / cap)


def credential_relevance() -> float:
    """Credential relevance to the request — neutral baseline (swap-point)."""
    return CREDENTIAL_RELEVANCE_BASELINE


def reputation_score() -> float:
    """Attestor reputation — neutral baseline (swap-point, Module 6)."""
    return REPUTATION_BASELINE


def compute_match_score(factors: dict[str, float]) -> tuple[float, dict[str, float]]:
    """Apply the locked weights to per-factor scores.

    Args:
        factors: Mapping with keys ``sector``, ``category``, ``credential``,
            ``availability``, ``reputation``, each in [0,1].

    Returns:
        The weighted sum rounded to 3 decimals, and the factor breakdown dict
        (persisted to ``AttestationOffer.score_breakdown``).
    """
    total = sum(factors[name] * weight for name, weight in WEIGHTS.items())
    return round(total, 3), factors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestation_scoring.py -q`
Expected: PASS (all).

- [ ] **Step 5: Lint + types**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/attestation/scoring.py backend/tests/unit/modules/test_attestation_scoring.py
git commit -m "feat(attestation): AMM scoring formula and per-factor functions"
```

---

### Task 3: Extend `CoiEntry` with conflict-link fields

**Files:**
- Modify: `backend/app/modules/attestation/schemas.py` (`class CoiEntry` ~`schemas.py:143`)
- Test: `backend/tests/unit/modules/test_attestation_scoring.py` is unrelated; add a small schema test in a new `backend/tests/unit/modules/test_coi_entry_schema.py`

**Interfaces:**
- Produces: `CoiEntry` now accepts optional `subject_id: UUID | None = None` and `subject_kind: Literal["user", "framework"] | None = None`. Existing fields unchanged; existing payloads (without the new fields) still validate.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/modules/test_coi_entry_schema.py`:

```python
"""Unit tests for the CoiEntry conflict-link extension.

Verifies the optional subject_id / subject_kind fields parse and that legacy
entries without them still validate (pre-launch, no backfill).

Maps to: spec §4 (CoI conflict-link schema).
"""

from __future__ import annotations

from uuid import uuid4

from app.modules.attestation.schemas import CoiEntry


def test_coi_entry_accepts_subject_link():
    subject = uuid4()
    entry = CoiEntry(
        entity="Acme Capital",
        entity_type="firm",
        relationship="financial",
        within_24mo=True,
        subject_id=subject,
        subject_kind="user",
    )
    assert entry.subject_id == subject
    assert entry.subject_kind == "user"


def test_coi_entry_without_subject_is_valid():
    entry = CoiEntry(
        entity="External Person",
        entity_type="individual",
        relationship="advisory",
        within_24mo=False,
    )
    assert entry.subject_id is None
    assert entry.subject_kind is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_coi_entry_schema.py -q`
Expected: FAIL — `CoiEntry` has no `subject_id` field (validation/attribute error).

- [ ] **Step 3: Extend the schema**

In `schemas.py`, replace `class CoiEntry` with:

```python
class CoiEntry(BaseModel):
    """One declared conflict-of-interest relationship disclosed by an applicant.

    ``subject_id`` optionally links the declaration to a known platform entity
    (a user or a framework). When set, the matching engine excludes this
    Attestor from any request whose target, target owner, or requestor matches
    the linked id. ``entity`` remains free text for external/unlinked parties.
    """

    entity: str
    entity_type: Literal["firm", "fund", "individual"]
    relationship: Literal["financial", "advisory", "employment"]
    within_24mo: bool
    subject_id: UUID | None = None
    subject_kind: Literal["user", "framework"] | None = None
```

Confirm `UUID` (from `uuid`) and `Literal` (from `typing`) are already imported at the top of `schemas.py`. They are used elsewhere in the file; if not present, add them.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_coi_entry_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + types**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/attestation/schemas.py backend/tests/unit/modules/test_coi_entry_schema.py
git commit -m "feat(attestation): link CoI declarations to platform entities for screening"
```

---

### Task 4: Scored eligibility + ranking (`_rank_eligible_attestors`) and offer wiring

**Files:**
- Modify: `backend/app/modules/attestation/matching_service.py` (replace `_matching_attestor_ids` ~`:684`; update `offer_next_cohort` ~`:77` and `:108`)
- Test: `backend/tests/unit/modules/test_attestation_matching_ranking.py` (new)
- Test: `backend/tests/integration/test_attestation_offers.py` (new or extend) — score persisted

**Interfaces:**
- Consumes: `scoring` module (Task 2); `AttestationOffer.match_score` / `score_breakdown` columns (Task 1); existing helpers `_excluded_attestor_ids`, `_target_owner_id`, `_platform_int_config`.
- Produces:
  - `ScoredCandidate` frozen dataclass with `user_id: UUID`, `score: float`, `breakdown: dict[str, float]`.
  - `async def _rank_eligible_attestors(db, *, attestation: Attestation, excluded_ids: set[UUID], limit: int, now: datetime) -> list[ScoredCandidate]`.
  - `offer_next_cohort` writes `match_score` + `score_breakdown` on each created `AttestationOffer`.

- [ ] **Step 1: Write the failing unit tests**

Create `backend/tests/unit/modules/test_attestation_matching_ranking.py`. This test seeds attestor profiles + an attestation directly and calls `_rank_eligible_attestors`. Follow the existing fixture pattern in `backend/tests/unit/modules/test_attestation_access_entitlement.py` (alembic head fixture, `_reset_state`, `async_session_factory`). Reuse that file's `migrated_database` / `clean_state` / `db_session` fixtures verbatim by copying them into this module (the suite already duplicates these per-file).

```python
"""Unit tests for scored Attestor eligibility, screening, and ranking.

Verifies the hard gates (expired CoI, CoI subject conflict, at-cap) and the
deterministic score-then-FIFO ordering of _rank_eligible_attestors.

Maps to: spec §2 (Eligibility + ranking).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import matching_service
from app.modules.attestation.models import (
    Attestation,
    AttestationOffer,
    AttestorProfile,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(Credential))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


@pytest.fixture
async def db_session(clean_state) -> AsyncIterator:
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _make_user(role: str, prefix: str) -> User:
    async with async_session_factory() as session:
        user = User(
            email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name=prefix,
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC)))
        await session.commit()
        await session.refresh(user)
    return user


async def _make_profile(
    user_id: UUID,
    *,
    specializations: list[str],
    jurisdictions: list[str],
    sectors: list[str] | None = None,
    framework_categories: list[str] | None = None,
    coi_declarations: list[dict] | None = None,
    coi_valid: bool = True,
    approved_at: datetime | None = None,
) -> None:
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        session.add(
            AttestorProfile(
                user_id=user_id,
                specializations=specializations,
                jurisdictions=jurisdictions,
                sectors=sectors or [],
                framework_categories=framework_categories or [],
                coi_declarations=coi_declarations or [],
                coi_signed_at=now if coi_valid else now - timedelta(days=400),
                coi_expires_at=(now + timedelta(days=365)) if coi_valid else now - timedelta(days=1),
                approved_at=approved_at or now,
                active=True,
            )
        )
        await session.commit()


async def _make_attestation(
    requestor_id: UUID,
    *,
    target_id: UUID,
    target_type: str = "framework",
    specializations: list[str],
    jurisdictions: list[str],
    attestor_id: UUID | None = None,
    status_value: str = "matching",
) -> Attestation:
    async with async_session_factory() as session:
        att = Attestation(
            target_type=target_type,
            target_id=target_id,
            requestor_id=requestor_id,
            attestor_id=attestor_id,
            status=status_value,
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=specializations,
            requested_jurisdictions=jurisdictions,
        )
        session.add(att)
        await session.commit()
        await session.refresh(att)
    return att


async def test_expired_coi_is_excluded(db_session):
    requestor = await _make_user("operator", "req")
    good = await _make_user("attestor", "good")
    expired = await _make_user("attestor", "expired")
    await _make_profile(good.id, specializations=["tax"], jurisdictions=["US"])
    await _make_profile(expired.id, specializations=["tax"], jurisdictions=["US"], coi_valid=False)
    att = await _make_attestation(
        requestor.id, target_id=uuid4(), target_type="contributor",
        specializations=["tax"], jurisdictions=["US"],
    )
    ranked = await matching_service._rank_eligible_attestors(
        db_session, attestation=att, excluded_ids={requestor.id}, limit=10, now=datetime.now(UTC),
    )
    ids = {c.user_id for c in ranked}
    assert good.id in ids
    assert expired.id not in ids


async def test_coi_subject_conflict_excluded(db_session):
    requestor = await _make_user("operator", "req")
    owner = await _make_user("contributor", "owner")
    conflicted = await _make_user("attestor", "conf")
    clean = await _make_user("attestor", "clean")
    async with async_session_factory() as s:
        fw = Framework(
            contributor_id=owner.id, title="T", description="d", status="published",
            category="compliance", tags=["t"], price=Decimal("1.00"),
            license_types=["single_user"], published_at=datetime.now(UTC),
        )
        s.add(fw)
        await s.commit()
        await s.refresh(fw)
    await _make_profile(
        conflicted.id, specializations=["tax"], jurisdictions=["US"],
        coi_declarations=[{
            "entity": "x", "entity_type": "firm", "relationship": "financial",
            "within_24mo": True, "subject_id": str(owner.id), "subject_kind": "user",
        }],
    )
    await _make_profile(clean.id, specializations=["tax"], jurisdictions=["US"])
    att = await _make_attestation(
        requestor.id, target_id=fw.id, target_type="framework",
        specializations=["tax"], jurisdictions=["US"],
    )
    excluded = await matching_service._excluded_attestor_ids(db_session, att)
    ranked = await matching_service._rank_eligible_attestors(
        db_session, attestation=att, excluded_ids=excluded, limit=10, now=datetime.now(UTC),
    )
    ids = {c.user_id for c in ranked}
    assert clean.id in ids
    assert conflicted.id not in ids


async def test_at_cap_attestor_excluded(db_session):
    requestor = await _make_user("operator", "req")
    busy = await _make_user("attestor", "busy")
    await _make_profile(busy.id, specializations=["tax"], jurisdictions=["US"])
    async with async_session_factory() as s:
        s.add(PlatformConfig(key="attestation_concurrency_cap", value="1"))
        await s.commit()
    # one active assignment already at cap=1
    await _make_attestation(
        requestor.id, target_id=uuid4(), target_type="contributor",
        specializations=["tax"], jurisdictions=["US"],
        attestor_id=busy.id, status_value="accepted",
    )
    att = await _make_attestation(
        requestor.id, target_id=uuid4(), target_type="contributor",
        specializations=["tax"], jurisdictions=["US"],
    )
    ranked = await matching_service._rank_eligible_attestors(
        db_session, attestation=att, excluded_ids={requestor.id}, limit=10, now=datetime.now(UTC),
    )
    assert busy.id not in {c.user_id for c in ranked}


async def test_ranking_orders_by_score_then_fifo(db_session):
    requestor = await _make_user("operator", "req")
    # high: matches sector fully; low: matches none of sector but still passes overlap
    high = await _make_user("attestor", "high")
    low = await _make_user("attestor", "low")
    older = await _make_user("attestor", "older")
    base = datetime.now(UTC)
    await _make_profile(
        high.id, specializations=["tax"], jurisdictions=["US"],
        sectors=["tax"], approved_at=base,
    )
    await _make_profile(
        low.id, specializations=["tax"], jurisdictions=["US"],
        sectors=[], approved_at=base,
    )
    # same scoring profile as `low` but approved earlier -> FIFO ahead of low
    await _make_profile(
        older.id, specializations=["tax"], jurisdictions=["US"],
        sectors=[], approved_at=base - timedelta(days=1),
    )
    att = await _make_attestation(
        requestor.id, target_id=uuid4(), target_type="contributor",
        specializations=["tax"], jurisdictions=["US"],
    )
    ranked = await matching_service._rank_eligible_attestors(
        db_session, attestation=att, excluded_ids={requestor.id}, limit=10, now=base,
    )
    order = [c.user_id for c in ranked]
    assert order[0] == high.id          # higher sector score first
    assert order.index(older.id) < order.index(low.id)  # tie broken by approved_at
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestation_matching_ranking.py -q`
Expected: FAIL — `_rank_eligible_attestors` does not exist.

- [ ] **Step 3: Implement `_rank_eligible_attestors` and remove `_matching_attestor_ids`**

In `matching_service.py`:

a) Add imports at the top (after the existing imports):

```python
from dataclasses import dataclass

from app.modules.attestation import scoring
```

b) Add the active-assignment status set near the other module constants (after `TERMINAL_OFFER_STATUSES`):

```python
ACTIVE_ASSIGNMENT_STATUSES = {"accepted", "report_submitted", "disputed"}
DEFAULT_CONCURRENCY_CAP = 5
```

c) Replace the entire `_matching_attestor_ids` function with:

```python
@dataclass(frozen=True)
class ScoredCandidate:
    """A scored, eligible Attestor candidate for one Attestation request."""

    user_id: UUID
    score: float
    breakdown: dict[str, float]


def _coi_conflict_subjects(attestation: Attestation, owner_id: UUID | None) -> set[str]:
    """Return the string ids a CoI declaration must avoid to remain eligible."""
    subjects = {str(attestation.target_id), str(attestation.requestor_id)}
    if owner_id is not None:
        subjects.add(str(owner_id))
    return subjects


def _is_coi_conflicted(
    coi_declarations: list[dict[str, object]],
    conflict_subjects: set[str],
    *,
    attestor_id: UUID,
) -> bool:
    """Check whether any declaration links to a conflicting platform entity.

    Malformed entries (missing/invalid subject_id) are skipped and logged; they
    never cause exclusion (deny-by-default applies to genuine conflicts, not to
    data noise).
    """
    for entry in coi_declarations:
        raw = entry.get("subject_id") if isinstance(entry, dict) else None
        if raw is None:
            continue
        try:
            subject = str(UUID(str(raw)))
        except (ValueError, TypeError):
            logger.bind(
                module="attestation",
                action="coi_conflict_screen",
                attestor_id=attestor_id,
            ).warning("coi_declaration_malformed_subject_id")
            continue
        if subject in conflict_subjects:
            return True
    return False


async def _framework_category(db: AsyncSession, attestation: Attestation) -> str | None:
    """Return the target framework category, or None for non-framework targets."""
    if attestation.target_type != "framework":
        return None
    return await db.scalar(
        select(Framework.category).where(Framework.id == attestation.target_id)
    )


async def _active_assignment_count(db: AsyncSession, attestor_id: UUID) -> int:
    """Count an Attestor's assignments in an active (content-holding) status."""
    count = await db.scalar(
        select(func.count())
        .select_from(Attestation)
        .where(
            Attestation.attestor_id == attestor_id,
            Attestation.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        )
    )
    return int(count or 0)


async def _rank_eligible_attestors(
    db: AsyncSession,
    *,
    attestation: Attestation,
    excluded_ids: set[UUID],
    limit: int,
    now: datetime,
) -> list[ScoredCandidate]:
    """Score and rank eligible Attestors for an Attestation request (§3.1–§3.2).

    Stage 1 (SQL) hard-filters the pool: active profile, specialization +
    jurisdiction overlap, not excluded, and a valid (signed, unexpired) CoI.
    Stage 2 (Python) drops CoI-conflicted and at-cap candidates, then scores the
    survivors with the weighted AMM formula. Results are sorted by score
    descending, then ``approved_at`` ascending, then ``user_id`` for a
    deterministic, FIFO-fair cohort.

    Args:
        db: Async session.
        attestation: The request being matched.
        excluded_ids: Users barred from this request (requestor, owner,
            already-offered).
        limit: Maximum candidates to return (the cohort size).
        now: Reference time for CoI-expiry comparison.

    Returns:
        Up to ``limit`` ScoredCandidate rows, best first.
    """
    query = (
        select(AttestorProfile)
        .where(
            AttestorProfile.active.is_(True),
            AttestorProfile.specializations.op("&&")(
                sql_cast(attestation.requested_specializations, ARRAY(Text))
            ),
            AttestorProfile.jurisdictions.op("&&")(
                sql_cast(attestation.requested_jurisdictions, ARRAY(Text))
            ),
            AttestorProfile.coi_signed_at.is_not(None),
            AttestorProfile.coi_expires_at > now,
        )
    )
    if excluded_ids:
        query = query.where(AttestorProfile.user_id.not_in(excluded_ids))
    profiles = list((await db.execute(query)).scalars().all())
    if not profiles:
        return []

    owner_id = await _target_owner_id(db, attestation)
    conflict_subjects = _coi_conflict_subjects(attestation, owner_id)
    framework_category = await _framework_category(db, attestation)
    cap = await _platform_int_config(
        db,
        key="attestation_concurrency_cap",
        default=DEFAULT_CONCURRENCY_CAP,
        minimum=1,
    )

    scored: list[tuple[float, datetime, UUID, ScoredCandidate]] = []
    for profile in profiles:
        if _is_coi_conflicted(
            profile.coi_declarations,
            conflict_subjects,
            attestor_id=profile.user_id,
        ):
            continue
        active_count = await _active_assignment_count(db, profile.user_id)
        if active_count >= cap:
            continue
        factors = {
            "sector": scoring.sector_alignment(
                attestation.requested_specializations,
                profile.sectors,
                profile.specializations,
            ),
            "category": scoring.category_match(
                framework_category, profile.framework_categories
            ),
            "credential": scoring.credential_relevance(),
            "availability": scoring.availability_score(active_count, cap),
            "reputation": scoring.reputation_score(),
        }
        score, breakdown = scoring.compute_match_score(factors)
        scored.append(
            (
                score,
                profile.approved_at,
                profile.user_id,
                ScoredCandidate(
                    user_id=profile.user_id, score=score, breakdown=breakdown
                ),
            )
        )

    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [row[3] for row in scored[:limit]]
```

d) In `offer_next_cohort`, replace the `_matching_attestor_ids(...)` call (the block assigning `candidate_ids`) with:

```python
    candidates = await _rank_eligible_attestors(
        db,
        attestation=attestation,
        excluded_ids=excluded_ids,
        limit=cohort_size,
        now=current_time,
    )
    if not candidates:
        attestation.status = "needs_admin"
        await write_audit(
            db=db,
            actor_id=None,
            action="attestation_needs_admin",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"reason": "matching_cohorts_exhausted"},
        )
        logger.bind(
            module="attestation",
            action="offer_next_cohort",
            attestation_id=attestation.id,
        ).warning("attestation_needs_admin")
        return []
```

e) Replace the offer-construction list + audit metadata (the `offers = [...]` block and the `attestation_offered` audit) with:

```python
    cohort_index = await _next_cohort_index(db, attestation.id)
    expires_at = current_time + timedelta(hours=offer_hours)
    offers = [
        AttestationOffer(
            attestation_id=attestation.id,
            attestor_id=candidate.user_id,
            cohort_index=cohort_index,
            status="offered",
            offered_at=current_time,
            expires_at=expires_at,
            match_score=candidate.score,
            score_breakdown=candidate.breakdown,
        )
        for candidate in candidates
    ]
    db.add_all(offers)
    attestation.status = "offered"
    await write_audit(
        db=db,
        actor_id=None,
        action="attestation_offered",
        target_type="attestation",
        target_id=attestation.id,
        metadata={
            "cohort_index": cohort_index,
            "attestor_ids": [str(c.user_id) for c in candidates],
            "scores": {str(c.user_id): c.score for c in candidates},
            "expires_at": expires_at.isoformat(),
        },
    )
    return offers
```

Note: `match_score=candidate.score` assigns a `float` to a `Numeric` column — SQLAlchemy/psycopg coerce it; the stored value is the 3-dp rounded score. If mypy objects, wrap with `Decimal(str(candidate.score))` and import `Decimal` from `decimal`.

- [ ] **Step 4: Run the unit tests**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestation_matching_ranking.py -q`
Expected: PASS (all four).

- [ ] **Step 5: Write the integration test for score persistence**

Add to `backend/tests/integration/test_attestation_offers.py` (create if absent, mirroring the fixture style of `tests/integration/test_attestation_access.py`). One test:

```python
async def test_offer_persists_match_score(db_session):
    """offer_next_cohort stores match_score + score_breakdown on each offer.

    Enforces spec §5 (score persistence).
    """
    # seed: one operator requestor, one eligible attestor profile, a matching
    # attestation in status "matching", then call offer_next_cohort and assert
    # the created AttestationOffer rows have non-null match_score and a
    # score_breakdown dict containing all five factor keys.
```

Implement the test body using the same `_make_user` / `_make_profile` / `_make_attestation` helpers as Task 4 Step 1 (copy them into this integration module or import from a shared factory if the suite has one — check `tests/factories/`). After calling `await matching_service.offer_next_cohort(db_session, attestation_id=att.id)`, query the offers and assert:

```python
    offers = await matching_service.offer_next_cohort(db_session, attestation_id=att.id)
    assert offers
    for offer in offers:
        assert offer.match_score is not None
        assert set(offer.score_breakdown) == {
            "sector", "category", "credential", "availability", "reputation",
        }
```

- [ ] **Step 6: Run the integration test**

Run: `cd backend && uv run pytest tests/integration/test_attestation_offers.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full attestation suite to confirm no regression**

Run: `cd backend && uv run pytest tests/unit/modules/test_attestation_matching_ranking.py tests/integration/test_attestation_access.py tests/unit/modules/test_attestation_access_entitlement.py -q`
Expected: PASS — the cohort/access flow still works with the swapped selector.

- [ ] **Step 8: Lint + types (whole repo)**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add backend/app/modules/attestation/matching_service.py backend/tests/unit/modules/test_attestation_matching_ranking.py backend/tests/integration/test_attestation_offers.py
git commit -m "feat(attestation): weighted AMM scoring with CoI and availability screening"
```

---

### Task 5: CoI re-sign reminder Beat task

**Files:**
- Modify: `backend/app/modules/attestation/notifications.py` (add two functions near the end)
- Modify: `backend/app/modules/attestation/matching_service.py` (add `send_coi_resign_reminders`)
- Modify: `backend/app/workers/tasks/attestation_beat.py` (add wrapper)
- Modify: `backend/app/workers/beat_schedule.py` (add daily entry)
- Test: `backend/tests/unit/workers/test_attestation_coi_reminder.py` (new)

**Interfaces:**
- Consumes: `AttestorProfile.coi_reminder_sent_at` (Task 1).
- Produces:
  - `notifications.notify_coi_expiring(user_id: UUID, *, expires_at: datetime) -> None`
  - `notifications.notify_coi_lapsed(user_id: UUID, *, expires_at: datetime) -> None`
  - `async def matching_service.send_coi_resign_reminders(db, *, now: datetime | None = None) -> int` (returns count of reminders sent)
  - Celery task `app.workers.tasks.attestation_beat.send_coi_resign_reminders`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/workers/test_attestation_coi_reminder.py`:

```python
"""Unit tests for the CoI re-sign reminder service.

Verifies the 30-day-before and lapsed windows fire once per cycle and that a
re-run is idempotent.

Maps to: spec §6 (CoI re-sign reminder Beat task).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import matching_service
from app.modules.attestation.models import AttestorProfile
from app.modules.auth.models import User, UserRole

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


@pytest.fixture
async def db_session(clean_state) -> AsyncIterator:
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _attestor_with_expiry(expires_at: datetime, signed_at: datetime) -> UUID:
    async with async_session_factory() as s:
        user = User(
            email=f"att-{uuid4().hex[:8]}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="att",
            email_verified=True,
        )
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role="attestor", approved_at=datetime.now(UTC)))
        s.add(
            AttestorProfile(
                user_id=user.id,
                specializations=["tax"],
                jurisdictions=["US"],
                coi_signed_at=signed_at,
                coi_expires_at=expires_at,
                active=True,
            )
        )
        await s.commit()
    return user.id


@pytest.fixture(autouse=True)
def _stub_notifications(monkeypatch):
    sent: list[tuple[str, UUID]] = []
    monkeypatch.setattr(
        matching_service.attestation_notifications,
        "notify_coi_expiring",
        lambda user_id, *, expires_at: sent.append(("expiring", user_id)),
    )
    monkeypatch.setattr(
        matching_service.attestation_notifications,
        "notify_coi_lapsed",
        lambda user_id, *, expires_at: sent.append(("lapsed", user_id)),
    )
    return sent


async def test_reminder_within_30_days(db_session, _stub_notifications):
    now = datetime.now(UTC)
    uid = await _attestor_with_expiry(now + timedelta(days=10), now - timedelta(days=355))
    count = await matching_service.send_coi_resign_reminders(db_session, now=now)
    assert count == 1
    assert ("expiring", uid) in _stub_notifications
    row = await db_session.scalar(
        select(AttestorProfile.coi_reminder_sent_at).where(AttestorProfile.user_id == uid)
    )
    assert row is not None


async def test_reminder_lapsed(db_session, _stub_notifications):
    now = datetime.now(UTC)
    uid = await _attestor_with_expiry(now - timedelta(days=2), now - timedelta(days=367))
    count = await matching_service.send_coi_resign_reminders(db_session, now=now)
    assert count == 1
    assert ("lapsed", uid) in _stub_notifications


async def test_reminder_idempotent_same_cycle(db_session, _stub_notifications):
    now = datetime.now(UTC)
    await _attestor_with_expiry(now + timedelta(days=10), now - timedelta(days=355))
    first = await matching_service.send_coi_resign_reminders(db_session, now=now)
    second = await matching_service.send_coi_resign_reminders(db_session, now=now + timedelta(hours=1))
    assert first == 1
    assert second == 0


async def test_no_reminder_when_far_from_expiry(db_session, _stub_notifications):
    now = datetime.now(UTC)
    await _attestor_with_expiry(now + timedelta(days=200), now - timedelta(days=165))
    count = await matching_service.send_coi_resign_reminders(db_session, now=now)
    assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/workers/test_attestation_coi_reminder.py -q`
Expected: FAIL — `send_coi_resign_reminders` / `notify_coi_expiring` do not exist.

- [ ] **Step 3: Add the notification functions**

In `notifications.py`, add the imports needed (`from datetime import datetime`; `dispatch_project_notification` is already importable as `from app.workers.tasks.project_notifications import dispatch_project_notification` — check the top of the file and reuse the existing import). Append:

```python
def notify_coi_expiring(user_id: UUID, *, expires_at: datetime) -> None:
    """Notify an Attestor their CoI declaration expires within 30 days."""
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type="attestor_coi_expiring",
            title="Your conflict-of-interest declaration is expiring",
            body=(
                "Re-sign your conflict-of-interest declaration before it expires "
                "to keep receiving attestation requests."
            ),
            payload={"expires_at": expires_at.isoformat()},
            link="/attestor/onboarding",
            dedupe_key=f"attestor_coi_expiring:{user_id}:{expires_at.isoformat()}",
        )
    except Exception as exc:
        logger.bind(
            module="attestation",
            action="queue_coi_expiring_notification",
            user_id=user_id,
        ).error("notification_dispatch_failed", error=str(exc))


def notify_coi_lapsed(user_id: UUID, *, expires_at: datetime) -> None:
    """Notify an Attestor their CoI declaration has lapsed."""
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type="attestor_coi_lapsed",
            title="Your conflict-of-interest declaration has lapsed",
            body=(
                "Your conflict-of-interest declaration has expired. Re-sign it to "
                "resume receiving attestation requests."
            ),
            payload={"expires_at": expires_at.isoformat()},
            link="/attestor/onboarding",
            dedupe_key=f"attestor_coi_lapsed:{user_id}:{expires_at.isoformat()}",
        )
    except Exception as exc:
        logger.bind(
            module="attestation",
            action="queue_coi_lapsed_notification",
            user_id=user_id,
        ).error("notification_dispatch_failed", error=str(exc))
```

- [ ] **Step 4: Add `send_coi_resign_reminders` to `matching_service.py`**

Add this constant near the other constants:

```python
COI_REMINDER_LEAD_DAYS = 30
```

Add the service function (uses the already-imported `attestation_notifications`, `select`, `datetime`, `timedelta`, `UTC`, `logger`, `AttestorProfile`):

```python
async def send_coi_resign_reminders(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Send CoI re-sign reminders for expiring or lapsed Attestor declarations.

    For each active profile with a CoI expiry, sends one reminder per cycle:
    a 30-day-before notice while still valid, or a lapsed notice once expired.
    ``coi_reminder_sent_at`` dedupes within a cycle — a profile is reminded
    again only after its timestamp predates the current cycle's lead window
    (i.e. after a re-sign pushes the expiry out). Idempotent: a same-day re-run
    sends nothing.

    Args:
        db: Async session.
        now: Reference time (defaults to current UTC).

    Returns:
        The number of reminders sent.
    """
    current_time = now or datetime.now(UTC)
    lead_window = timedelta(days=COI_REMINDER_LEAD_DAYS)
    rows = (
        await db.execute(
            select(AttestorProfile).where(
                AttestorProfile.active.is_(True),
                AttestorProfile.coi_expires_at.is_not(None),
            )
        )
    ).scalars().all()

    sent = 0
    for profile in rows:
        expires_at = profile.coi_expires_at
        if expires_at is None:
            continue
        reminder_window_start = expires_at - lead_window
        # Already reminded for this cycle if the timestamp falls in/after the
        # window-start of the current expiry cycle.
        already_reminded = (
            profile.coi_reminder_sent_at is not None
            and profile.coi_reminder_sent_at >= reminder_window_start
        )
        if already_reminded:
            continue
        if current_time >= expires_at:
            attestation_notifications.notify_coi_lapsed(
                profile.user_id, expires_at=expires_at
            )
        elif current_time >= reminder_window_start:
            attestation_notifications.notify_coi_expiring(
                profile.user_id, expires_at=expires_at
            )
        else:
            continue
        profile.coi_reminder_sent_at = current_time
        sent += 1

    if sent:
        await db.commit()
    logger.bind(
        module="attestation",
        action="send_coi_resign_reminders",
    ).info("coi_reminders_sent", count=sent)
    return sent
```

- [ ] **Step 5: Run the reminder unit tests**

Run: `cd backend && uv run pytest tests/unit/workers/test_attestation_coi_reminder.py -q`
Expected: PASS (all four).

- [ ] **Step 6: Add the Celery wrapper**

In `attestation_beat.py`, add an async helper + task wrapper following the existing pattern:

```python
async def _send_coi_resign_reminders() -> int:
    """Send CoI re-sign reminders for expiring/lapsed Attestor declarations."""
    async with async_session_factory() as db:
        return await matching_service.send_coi_resign_reminders(db)


@app.task(bind=True)  # type: ignore[untyped-decorator]
def send_coi_resign_reminders(self: Any) -> dict[str, int]:
    """Celery wrapper for the daily CoI re-sign reminder sweep."""
    log = logger.bind(
        module="attestation",
        action="send_coi_resign_reminders",
        task_id=self.request.id,
    )
    log.info("task_started")
    reminded_count = run_async(_send_coi_resign_reminders())
    result = {"reminded_count": reminded_count}
    log.info("task_completed", result=result)
    return result
```

- [ ] **Step 7: Register the daily schedule**

In `beat_schedule.py`, add inside `BEAT_SCHEDULE` (next to the other attestation entries):

```python
    "coi-resign-reminders-daily": {
        "task": "app.workers.tasks.attestation_beat.send_coi_resign_reminders",
        "schedule": crontab(hour=2, minute=0),
    },
```

- [ ] **Step 8: Lint + types (whole repo)**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add backend/app/modules/attestation/notifications.py backend/app/modules/attestation/matching_service.py backend/app/workers/tasks/attestation_beat.py backend/app/workers/beat_schedule.py backend/tests/unit/workers/test_attestation_coi_reminder.py
git commit -m "feat(attestation): daily CoI re-sign reminder Beat task"
```

---

## Self-Review

**Spec coverage:**
- §3.2 weighted scoring → Task 2 (`scoring.py`) + Task 4 (factor wiring). ✅
- §3.1 conflict screening (subject_id) → Task 3 (schema) + Task 4 (`_is_coi_conflicted`). ✅
- Availability cap → Task 4 (`_active_assignment_count`, config). ✅
- CoI enforcement (expired excluded) → Task 4 (SQL filter `coi_expires_at > now`). ✅
- CoI re-sign reminders → Task 5. ✅
- Score persistence + breakdown → Task 1 (columns) + Task 4 (offer wiring) + integration test. ✅
- `coi_reminder_sent_at` dedup → Task 1 (column) + Task 5 (logic + test). ✅
- Migration up/down → Task 1 Step 3. ✅
- `framework_categories` category source (spec refinement) → Task 2 `category_match` + Task 4 wiring. ✅
- Out-of-scope items (firm/org name, real reputation/credential, request sector field) → intentionally untouched; constants documented as swap-points. ✅

**Placeholder scan:** Task 4 Step 5 integration-test body is described as a guided stub rather than verbatim because it depends on whether `tests/integration/test_attestation_offers.py` exists and on the suite's factory availability — the assertions and the helper source (Task 4 Step 1) are concrete; the implementer copies the helpers. All other code blocks are complete. No "TBD"/"add error handling"/"similar to Task N".

**Type consistency:** `ScoredCandidate(user_id, score, breakdown)` defined in Task 4, consumed in Task 4 offer wiring with `.user_id`/`.score`/`.breakdown` — consistent. `send_coi_resign_reminders(db, *, now=None) -> int` defined Task 5, called by wrapper with no `now` (defaults) — consistent. `notify_coi_expiring`/`notify_coi_lapsed` signatures match the stub in the reminder test. `compute_match_score` returns `(float, dict)` — used as `score, breakdown` in Task 4. Weight keys (`sector/category/credential/availability/reputation`) identical across `WEIGHTS`, factor dict, and the breakdown assertion. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-30-attestation-module-3-amm-matching.md`.

Per the standing workflow on this repo: the human's own agent implements + commits each task; the reviewer (this session) diffs each committed task, runs the gates (`uv run pytest <task tests>`, whole-repo `uv run ruff check .`, `uv run mypy app`), and triages findings. No subagent dispatch from here unless explicitly requested.
