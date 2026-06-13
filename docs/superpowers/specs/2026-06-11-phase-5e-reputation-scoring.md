# Phase 5e — Reputation Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute a 0–100 `ReputationScore` for every framework, contributor, and operator by aggregating existing source tables on a daily schedule, and surface it (publicly for framework/contributor, contextually for operator).

**Architecture:** New `app/modules/reputation/` module. A `reputation_scores` table holds one upserted row per `(subject_type, subject_id)`. A Celery Beat task `recompute_reputation` pull-aggregates source tables (reviews, attestations, transactions, licenses, disputes, users), normalizes each factor to 0–1, applies per-subject weights (from `platform_config`), shrinks toward a neutral prior, marks low-evidence subjects provisional, and upserts. Read endpoints expose headline score + factor labels (not raw weights). No money movement.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Alembic, Celery + Beat, pytest/pytest-asyncio, loguru. Decimal-only math (no float).

**Source spec:** this checked-in spec is the source for Phase 5e. It maps to FRD `ReputationScore`, FRD `BR-ATT-005`, TDD `reputation_scores`, and the TDD `recalculate_reputation` worker. Reuse patterns: `_platform_decimal_config` (`app/modules/financials/service.py:134`), `write_audit` (`app/core/audit.py:18`), `BEAT_SCHEDULE` (`app/workers/beat_schedule.py`), migration template (`migrations/versions/2026_06_10_0013_*`), admin config validation (`app/modules/admin/service.py:368+`), Celery task pattern (`app/workers/tasks/projects_beat.py`, `run_async` + `app.task`).

---

## File Structure

- `backend/app/modules/reputation/__init__.py` — empty package marker.
- `backend/app/modules/reputation/models.py` — `ReputationScore` ORM.
- `backend/app/modules/reputation/weights.py` — load + validate weights/thresholds/prior/decay from `platform_config`; pure config access.
- `backend/app/modules/reputation/factors.py` — per-subject factor aggregators (each returns normalized 0–1 + evidence count); one function per subject_type.
- `backend/app/modules/reputation/service.py` — compose factors → score (weighting, shrinkage, provisional, decay), upsert, and read helpers.
- `backend/app/modules/reputation/schemas.py` — `ReputationResponse` (headline + factor labels).
- `backend/app/modules/reputation/router.py` — module-local `/reputation/*` read endpoints + admin recompute. `backend/app/main.py` adds the `/v1` prefix like the existing routers.
- `backend/app/workers/tasks/reputation.py` — replace stub with `recompute_reputation` Beat task + single-subject recompute.
- `backend/migrations/versions/2026_06_11_0017_reputation_scores.py` — table + enum + `platform_config` seeds.
- Modify: `backend/app/workers/beat_schedule.py` (add daily entry), `backend/app/main.py` (mount router), `backend/app/modules/admin/service.py` (config validation for reputation keys), `backend/app/modules/admin/router.py` (recompute endpoint optional — placed in reputation router instead), `backend/app/modules/explore/schemas.py` + `service.py` (framework card + contributor profile reputation), `backend/app/modules/projects/*` (operator reputation on proposal/detail surfaces — Task 6).
- Tests under `backend/tests/unit/modules/test_reputation_*.py` and `backend/tests/integration/test_reputation_endpoints.py`.

Current repo alignment, verified on 2026-06-11:

- Latest migration is `2026_06_11_0016_rarity_override_state.py`; Task 1 must create `2026_06_11_0017_reputation_scores.py` with `down_revision = "2026_06_11_0016"`. Still confirm with `ls backend/migrations/versions | sort | tail -3` before writing because migrations may move while this plan waits.
- ORM models inherit from `app.core.database.Base`; do not import `app.shared.base`.
- `License` lives in `app.modules.frameworks.models`, not `app.modules.financials.models`.
- Routers use module-local prefixes and are mounted in `backend/app/main.py` with `prefix="/v1"`.
- `backend/tests/conftest.py` currently exposes a `client` fixture only. Test snippets below are behavior contracts; implement them using the current harness (`client`, `async_session_factory`, inline ORM setup) or add explicit local fixtures in the same test file before using factory-style names.

Test snippet convention: names such as `db_session`, `async_client`, `framework_factory`, `review_factory`, `license_factory`, `user_factory`, and `auth_headers` are placeholders for the shape of the test. They are not current global fixtures. When implementing a slice, either define those helpers locally in the test file first, or rewrite the snippet to match the nearby tests' inline ORM setup. Do not add hidden dependencies on non-existent global fixtures.

---

## Task 1: Schema foundation + platform_config seeds

**Files:**

- Create: `backend/app/modules/reputation/__init__.py`
- Create: `backend/app/modules/reputation/models.py`
- Create: `backend/migrations/versions/2026_06_11_0017_reputation_scores.py`
- Test: `backend/tests/integration/test_reputation_schema.py`

- [ ] **Step 1: Write the ORM model**

`backend/app/modules/reputation/models.py`:

```python
"""Reputation scoring ORM models.

Stores one upserted score row per (subject_type, subject_id). Maps to
FRD ReputationScore and full-spec §10. See Phase 5e design spec.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReputationScore(Base):
    """Latest computed reputation for one subject."""

    __tablename__ = "reputation_scores"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    components: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_provisional: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", name="uq_reputation_subject"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_reputation_score_range"),
        CheckConstraint(
            "subject_type IN ('framework','contributor','operator')",
            name="ck_reputation_subject_type",
        ),
        Index("ix_reputation_subject_type_score", "subject_type", score.desc().nullslast()),
    )
```

`gen_random_uuid()` is already used by other migrations so the extension is present.

- [ ] **Step 2: Write the migration**

`backend/migrations/versions/2026_06_11_0017_reputation_scores.py`:

```python
"""Create reputation_scores table and seed reputation platform_config.

Revision ID: 2026_06_11_0017
Revises: 2026_06_11_0016
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_11_0017"
down_revision: str | Sequence[str] | None = "2026_06_11_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED = {
    # JSON weight maps (factors sum to 1.0 per subject_type)
    "reputation_weights_framework": '{"reviews":0.35,"attestations":0.30,"adoption":0.35,"completion":0.00,"recency":0.00}',
    "reputation_weights_contributor": '{"verification":0.15,"framework_performance":0.30,"reviews_received":0.20,"attestations_received":0.20,"activity":0.15}',
    "reputation_weights_operator": '{"purchase_activity":0.40,"license_compliance":0.25,"review_quality":0.20,"engagement":0.15}',
    "reputation_min_activity_framework": "3",
    "reputation_min_activity_contributor": "1",
    "reputation_min_activity_operator": "1",
    "reputation_prior": "0.5",
    "reputation_prior_strength_k": "5",
    "reputation_decay_halflife_days": "180",
    "reputation_dispute_penalty": "0.20",
}


def upgrade() -> None:
    op.create_table(
        "reputation_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("components", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_provisional", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("subject_type", "subject_id", name="uq_reputation_subject"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_reputation_score_range"),
        sa.CheckConstraint("subject_type IN ('framework','contributor','operator')", name="ck_reputation_subject_type"),
    )
    op.create_index("ix_reputation_subject_type_score", "reputation_scores", ["subject_type", sa.text("score DESC NULLS LAST")])
    for key, value in _SEED.items():
        op.execute(
            sa.text("INSERT INTO platform_config (key, value) VALUES (:k, :v) "
                    "ON CONFLICT (key) DO NOTHING").bindparams(k=key, v=value)
        )


def downgrade() -> None:
    for key in _SEED:
        op.execute(sa.text("DELETE FROM platform_config WHERE key = :k").bindparams(k=key))
    op.drop_index("ix_reputation_subject_type_score", table_name="reputation_scores")
    op.drop_table("reputation_scores")
```

- [ ] **Step 3: Register model import + write the schema test**

No central model-import registry exists in the current repo. If one is introduced before implementation, add `from app.modules.reputation import models as reputation_models  # noqa: F401` there. Otherwise the manual migration above is enough; do not create a model registry just for this slice.

`backend/tests/integration/test_reputation_schema.py`:

```python
"""Reputation schema migration smoke test."""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_reputation_scores_table_and_seeds(db_session):
    """Migration creates the table, constraints, and seeds reputation config."""
    cols = (await db_session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'reputation_scores'"
    ))).scalars().all()
    assert {"subject_type", "subject_id", "score", "components", "is_provisional"} <= set(cols)

    seeded = (await db_session.execute(text(
        "SELECT key FROM platform_config WHERE key LIKE 'reputation_%'"
    ))).scalars().all()
    assert "reputation_weights_framework" in seeded
    assert "reputation_prior" in seeded
```

Use the project's current test harness. Today there is no global `db_session` fixture; either add a local fixture backed by `app.core.database.async_session_factory` in this test file, or open an `async_session_factory()` session directly inside the test. Do not depend on missing factory fixtures.

- [ ] **Step 4: Run migration up/down + test**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all succeed, no errors.
Run: `cd backend && uv run pytest tests/integration/test_reputation_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/reputation backend/migrations/versions/2026_06_11_0017_reputation_scores.py backend/tests/integration/test_reputation_schema.py
git commit -m "feat(reputation): schema foundation + platform_config seeds"
```

---

## Task 2: Config loader + admin config validation

**Files:**

- Create: `backend/app/modules/reputation/weights.py`
- Modify: `backend/app/modules/admin/service.py` (add reputation keys to `_normalise_platform_config_value` + allowed-key set near line 31/368)
- Test: `backend/tests/unit/modules/test_reputation_weights.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/modules/test_reputation_weights.py`:

```python
"""Reputation config loader tests."""

from decimal import Decimal

import pytest

from app.modules.reputation import weights


@pytest.mark.asyncio
async def test_load_weights_defaults_when_unset(db_session):
    cfg = await weights.load_config(db_session, subject_type="framework")
    assert pytest.approx(float(sum(cfg.weights.values())), abs=1e-6) == 1.0
    assert cfg.prior == Decimal("0.5")
    assert cfg.min_activity >= 1


def test_validate_weights_rejects_non_unit_sum():
    with pytest.raises(ValueError):
        weights.validate_weight_map(
            {
                "reviews": Decimal("0.3"),
                "attestations": Decimal("0.3"),
                "adoption": Decimal("0.2"),
                "completion": Decimal("0.0"),
                "recency": Decimal("0.0"),
            },
            subject_type="framework",
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_reputation_weights.py -v`
Expected: FAIL (module `weights` not found).

- [ ] **Step 3: Implement the loader**

`backend/app/modules/reputation/weights.py`:

```python
"""Load and validate reputation weights/thresholds from platform_config."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.financials.models import PlatformConfig

_DEFAULT_WEIGHTS: dict[str, dict[str, str]] = {
    # Launch weights exclude completion/recency until real factor evidence exists.
    # Keep the keys so future recalibration can turn them on without schema churn.
    "framework": {"reviews": "0.35", "attestations": "0.30", "adoption": "0.35", "completion": "0.00", "recency": "0.00"},
    "contributor": {"verification": "0.15", "framework_performance": "0.30", "reviews_received": "0.20", "attestations_received": "0.20", "activity": "0.15"},
    "operator": {"purchase_activity": "0.40", "license_compliance": "0.25", "review_quality": "0.20", "engagement": "0.15"},
}
_DEFAULT_MIN_ACTIVITY = {"framework": 3, "contributor": 1, "operator": 1}


@dataclass(frozen=True)
class ReputationConfig:
    subject_type: str
    weights: dict[str, Decimal]
    min_activity: int
    prior: Decimal
    prior_strength_k: Decimal
    decay_halflife_days: int
    dispute_penalty: Decimal


def validate_weight_map(weights_map: dict[str, Decimal], *, subject_type: str) -> None:
    """Raise ValueError unless weights have the exact expected shape and sum."""
    expected = set(_DEFAULT_WEIGHTS[subject_type])
    actual = set(weights_map)
    if actual != expected:
        raise ValueError(
            f"reputation weights for {subject_type} must use keys {sorted(expected)}"
        )
    if any(w < 0 for w in weights_map.values()):
        raise ValueError("reputation weights must be non-negative")
    total = sum(weights_map.values())
    if abs(total - Decimal("1")) > Decimal("0.001"):
        raise ValueError(f"reputation weights must sum to 1.0 (got {total})")


async def _raw(db: AsyncSession, key: str) -> str | None:
    return await db.scalar(select(PlatformConfig.value).where(PlatformConfig.key == key))


async def load_config(db: AsyncSession, *, subject_type: str) -> ReputationConfig:
    raw_weights = await _raw(db, f"reputation_weights_{subject_type}")
    weights_map = (
        {k: Decimal(str(v)) for k, v in json.loads(raw_weights).items()}
        if raw_weights
        else {k: Decimal(v) for k, v in _DEFAULT_WEIGHTS[subject_type].items()}
    )
    validate_weight_map(weights_map, subject_type=subject_type)
    min_activity = int(await _raw(db, f"reputation_min_activity_{subject_type}") or _DEFAULT_MIN_ACTIVITY[subject_type])
    prior = Decimal(await _raw(db, "reputation_prior") or "0.5")
    k = Decimal(await _raw(db, "reputation_prior_strength_k") or "5")
    halflife = int(await _raw(db, "reputation_decay_halflife_days") or "180")
    penalty = Decimal(await _raw(db, "reputation_dispute_penalty") or "0.20")
    if min_activity < 1 or k < 0 or halflife < 1:
        raise ValueError("reputation min_activity, prior_strength_k, and halflife must be positive")
    if prior < 0 or prior > 1 or penalty < 0 or penalty > 1:
        raise ValueError("reputation prior and dispute penalty must be between 0 and 1")
    return ReputationConfig(subject_type, weights_map, min_activity, prior, k, halflife, penalty)
```

- [ ] **Step 4: Extend admin config validation**

In `backend/app/modules/admin/service.py`: add the reputation keys to the editable allow-list (the set near line 31) and a branch in `_normalise_platform_config_value` (mirror the `refund_window_hours`/`commission_rate` branches). Add:

```python
# near the allow-list constant
REPUTATION_WEIGHT_FACTORS = {
    "framework": {"reviews", "attestations", "adoption", "completion", "recency"},
    "contributor": {"verification", "framework_performance", "reviews_received", "attestations_received", "activity"},
    "operator": {"purchase_activity", "license_compliance", "review_quality", "engagement"},
}
REPUTATION_WEIGHT_KEYS = (
    "reputation_weights_framework",
    "reputation_weights_contributor",
    "reputation_weights_operator",
)
# inside _normalise_platform_config_value, before the final "unknown key" raise:
if key in REPUTATION_WEIGHT_KEYS:
    subject_type = key.removeprefix("reputation_weights_")
    expected = REPUTATION_WEIGHT_FACTORS[subject_type]
    try:
        parsed = {k: Decimal(str(v)) for k, v in json.loads(raw_value).items()}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{key} must be a JSON object of factor weights.") from exc
    if set(parsed) != expected:
        raise HTTPException(status_code=422, detail=f"{key} must contain exactly these factors: {sorted(expected)}.")
    total = sum(parsed.values())
    if any(v < 0 for v in parsed.values()) or abs(total - Decimal("1")) > Decimal("0.001"):
        raise HTTPException(status_code=422, detail=f"{key} weights must be non-negative and sum to 1.0.")
    return json.dumps({k: f"{v:.4f}" for k, v in parsed.items()})
if key == "reputation_prior":
    value = _parse_decimal_config(key, raw_value)
    if value < Decimal("0") or value > Decimal("1"):
        raise HTTPException(status_code=422, detail="reputation_prior must be between 0 and 1.")
    return _format_decimal_config(value.quantize(Decimal("0.0001")))
```

Also validate the scalar keys:

- `reputation_min_activity_*`: integer >= 1.
- `reputation_prior_strength_k`: decimal >= 0.
- `reputation_decay_halflife_days`: integer >= 1.
- `reputation_dispute_penalty`: decimal between 0 and 1.

Add the reputation keys (weights + `reputation_prior` + `reputation_min_activity_*` + `reputation_prior_strength_k` + `reputation_decay_halflife_days` + `reputation_dispute_penalty`) to whatever set gates "is this key editable" so the PATCH endpoint accepts them. Keep imports at module top rather than inline if the file style requires (move `import json` up; `Decimal` is already imported in the current service).

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/modules/test_reputation_weights.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/reputation/weights.py backend/app/modules/admin/service.py backend/tests/unit/modules/test_reputation_weights.py
git commit -m "feat(reputation): config loader + admin config validation"
```

---

## Task 3: Factor aggregators + compute engine

This is the math core. Factors return `(normalized_value: Decimal in [0,1], evidence_count: int)`. The engine combines them with weights + shrinkage and decides provisional.

**Files:**

- Create: `backend/app/modules/reputation/factors.py`
- Create: `backend/app/modules/reputation/service.py`
- Test: `backend/tests/unit/modules/test_reputation_engine.py`

- [ ] **Step 1: Write failing tests for the engine math**

`backend/tests/unit/modules/test_reputation_engine.py`:

```python
"""Reputation compute-engine math tests (pure, no DB)."""

from decimal import Decimal

from app.modules.reputation.service import FactorResult, combine_factors


def _cfg(weights, prior="0.5", k="5", min_activity=3):
    from app.modules.reputation.weights import ReputationConfig
    return ReputationConfig("framework", {f: Decimal(w) for f, w in weights.items()},
                            min_activity, Decimal(prior), Decimal(k), 180, Decimal("0.20"))


def test_no_evidence_is_provisional_and_near_prior():
    cfg = _cfg({"reviews": "1.0"})
    res = combine_factors(cfg, {"reviews": FactorResult(Decimal("0"), 0)})
    assert res.is_provisional is True
    # n=0 → score collapses to prior*100 = 50
    assert res.score == Decimal("50.00")


def test_strong_evidence_not_provisional_and_tracks_raw():
    cfg = _cfg({"reviews": "1.0"}, min_activity=3)
    res = combine_factors(cfg, {"reviews": FactorResult(Decimal("1.0"), 20)})
    assert res.is_provisional is False
    # n=20,k=5,prior=0.5,raw=1.0 → (20/25)*1 + (5/25)*0.5 = 0.9 → 90.00
    assert res.score == Decimal("90.00")


def test_weighted_sum_of_factors():
    cfg = _cfg({"reviews": "0.5", "attestations": "0.5"}, k="0", min_activity=1)
    res = combine_factors(cfg, {
        "reviews": FactorResult(Decimal("1.0"), 10),
        "attestations": FactorResult(Decimal("0.0"), 10),
    })
    # k=0 → no shrinkage; raw = 0.5*1 + 0.5*0 = 0.5 → 50.00
    assert res.score == Decimal("50.00")


def test_components_carry_labels():
    cfg = _cfg({"reviews": "1.0"}, min_activity=1)
    res = combine_factors(cfg, {"reviews": FactorResult(Decimal("0.9"), 10)})
    assert res.components["reviews"]["label"] in {"strong", "moderate", "weak"}
    assert "value" in res.components["reviews"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_reputation_engine.py -v`
Expected: FAIL (no `service` module / `combine_factors`).

- [ ] **Step 3: Implement the engine**

`backend/app/modules/reputation/service.py`:

```python
"""Reputation compute engine + persistence + reads.

Combines per-subject factor results into a 0-100 score with shrinkage toward a
neutral prior, provisional gating for low-evidence subjects, and an upsert into
reputation_scores. See Phase 5e design spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reputation.models import ReputationScore
from app.modules.reputation.weights import ReputationConfig

_TWO = Decimal("0.01")


@dataclass(frozen=True)
class FactorResult:
    value: Decimal          # normalized 0..1
    evidence: int           # evidence count contributing to this factor


@dataclass(frozen=True)
class ScoreResult:
    score: Decimal          # 0..100, two decimals
    components: dict
    is_provisional: bool
    evidence: int


def _label(value: Decimal) -> str:
    if value >= Decimal("0.66"):
        return "strong"
    if value >= Decimal("0.33"):
        return "moderate"
    return "weak"


def combine_factors(cfg: ReputationConfig, factors: dict[str, FactorResult]) -> ScoreResult:
    """Weight, shrink toward prior, and label factor results into a ScoreResult."""
    raw = Decimal("0")
    for name, weight in cfg.weights.items():
        fr = factors.get(name, FactorResult(Decimal("0"), 0))
        # clamp normalized value defensively
        v = min(Decimal("1"), max(Decimal("0"), fr.value))
        raw += weight * v
    total_evidence = sum(fr.evidence for fr in factors.values())
    n = Decimal(total_evidence)
    k = cfg.prior_strength_k
    denom = n + k
    shrunk = raw if denom == 0 else (n / denom) * raw + (k / denom) * cfg.prior
    score = (shrunk * Decimal("100")).quantize(_TWO, rounding=ROUND_HALF_UP)
    components = {
        name: {"value": str(min(Decimal("1"), max(Decimal("0"), factors.get(name, FactorResult(Decimal('0'), 0)).value)).quantize(Decimal("0.0001"))),
               "label": _label(factors.get(name, FactorResult(Decimal("0"), 0)).value)}
        for name in cfg.weights
    }
    is_provisional = total_evidence < cfg.min_activity
    return ScoreResult(score, components, is_provisional, total_evidence)


async def upsert_score(db: AsyncSession, *, subject_type: str, subject_id: UUID, result: ScoreResult) -> None:
    """Idempotently upsert a computed score row."""
    from datetime import UTC, datetime
    stmt = pg_insert(ReputationScore).values(
        subject_type=subject_type,
        subject_id=subject_id,
        score=result.score,
        components=result.components,
        is_provisional=result.is_provisional,
        last_calculated_at=datetime.now(UTC),
    ).on_conflict_do_update(
        constraint="uq_reputation_subject",
        set_={
            "score": result.score,
            "components": result.components,
            "is_provisional": result.is_provisional,
            "last_calculated_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)


async def get_score(db: AsyncSession, *, subject_type: str, subject_id: UUID) -> ReputationScore | None:
    return await db.scalar(
        select(ReputationScore).where(
            ReputationScore.subject_type == subject_type,
            ReputationScore.subject_id == subject_id,
        )
    )
```

- [ ] **Step 4: Run engine tests**

Run: `cd backend && uv run pytest tests/unit/modules/test_reputation_engine.py -v`
Expected: PASS (all four).

- [ ] **Step 5: Implement factor aggregators**

`backend/app/modules/reputation/factors.py`. Each function queries source tables and returns `dict[str, FactorResult]`. Normalize with bounded saturating curves (counts → `min(1, count/target)`; averages on 1–5 → `(avg-1)/4`). Penalties subtract from the relevant factor, bounded at 0.

```python
"""Per-subject reputation factor aggregators (normalized 0..1)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import Attestation
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License, Review
from app.modules.projects.models import Dispute, Milestone, Project, Proposal
from app.modules.reputation.service import FactorResult
from app.modules.reputation.weights import ReputationConfig

_REVIEW_TARGET = Decimal("10")     # reviews count to saturate
_ADOPTION_TARGET = Decimal("25")   # active licenses to saturate


def _avg_review_norm(avg: Decimal | None) -> Decimal:
    if avg is None:
        return Decimal("0")
    return max(Decimal("0"), min(Decimal("1"), (avg - Decimal("1")) / Decimal("4")))


def _saturating(count: int, target: Decimal) -> Decimal:
    return min(Decimal("1"), Decimal(count) / target)


async def framework_factors(db: AsyncSession, framework_id: UUID, cfg: ReputationConfig) -> dict[str, FactorResult]:
    avg, cnt = (await db.execute(
        select(func.avg(Review.score), func.count(Review.id)).where(Review.framework_id == framework_id)
    )).one()
    review_count = int(cnt or 0)
    reviews = FactorResult(_avg_review_norm(Decimal(str(avg)) if avg is not None else None), review_count)

    pos_att = int(await db.scalar(
        select(func.count(Attestation.id)).where(
            Attestation.target_type == "framework",
            Attestation.target_id == framework_id,
            Attestation.outcome.in_(("approved", "conditional")),
            Attestation.status.in_(("report_submitted", "closed")),
        )
    ) or 0)
    rej_att = int(await db.scalar(
        select(func.count(Attestation.id)).where(
            Attestation.target_type == "framework",
            Attestation.target_id == framework_id,
            Attestation.outcome == "rejected",
        )
    ) or 0)
    att_norm = max(Decimal("0"), _saturating(pos_att, Decimal("3")) - cfg.dispute_penalty * Decimal(rej_att))
    attestations = FactorResult(max(Decimal("0"), min(Decimal("1"), att_norm)), pos_att + rej_att)

    active_licenses = int(await db.scalar(
        select(func.count(License.id)).where(
            License.framework_id == framework_id, License.status == "active"
        )
    ) or 0)
    adoption = FactorResult(_saturating(active_licenses, _ADOPTION_TARGET), active_licenses)

    # completion + recency are real future factors but launch with zero weight.
    # They stay as explicit keys so config shape remains stable during recalibration.
    completion = FactorResult(Decimal("0.5"), 0)
    recency = FactorResult(Decimal("0.5"), 0)
    return {"reviews": reviews, "attestations": attestations, "adoption": adoption,
            "completion": completion, "recency": recency}


async def contributor_factors(db: AsyncSession, user_id: UUID, cfg: ReputationConfig) -> dict[str, FactorResult]:
    from app.modules.auth.models import User, UserRole
    user = await db.get(User, user_id)
    kyc_ok = bool(user and getattr(user, "kyc_status", None) == "verified")
    attestor_ok = bool(await db.scalar(
        select(UserRole.id).where(UserRole.user_id == user_id, UserRole.role == "attestor",
                                  UserRole.approved_at.is_not(None))
    ))
    verification = FactorResult(
        (Decimal("0.5") if kyc_ok else Decimal("0")) + (Decimal("0.5") if attestor_ok else Decimal("0")),
        (1 if kyc_ok else 0) + (1 if attestor_ok else 0),
    )

    # framework performance: avg of this contributor's framework scores already computed.
    from app.modules.reputation.models import ReputationScore
    fw_ids = (await db.execute(
        select(Framework.id).where(Framework.contributor_id == user_id, Framework.status == "published")
    )).scalars().all()
    perf_val, perf_n = Decimal("0"), 0
    if fw_ids:
        avg_score = await db.scalar(
            select(func.avg(ReputationScore.score)).where(
                ReputationScore.subject_type == "framework",
                ReputationScore.subject_id.in_(fw_ids),
                ReputationScore.is_provisional.is_(False),
            )
        )
        if avg_score is not None:
            perf_val = Decimal(str(avg_score)) / Decimal("100")
            perf_n = len(fw_ids)
    framework_performance = FactorResult(perf_val, perf_n)

    avg_recv, cnt_recv = (await db.execute(
        select(func.avg(Review.score), func.count(Review.id))
        .join(Framework, Framework.id == Review.framework_id)
        .where(Framework.contributor_id == user_id)
    )).one()
    reviews_received = FactorResult(_avg_review_norm(Decimal(str(avg_recv)) if avg_recv is not None else None), int(cnt_recv or 0))

    pos_att = int(await db.scalar(
        select(func.count(Attestation.id)).where(
            Attestation.target_type == "contributor", Attestation.target_id == user_id,
            Attestation.outcome.in_(("approved", "conditional")),
            Attestation.status.in_(("report_submitted", "closed")),
        )
    ) or 0)
    attestations_received = FactorResult(_saturating(pos_att, Decimal("2")), pos_att)

    proposals = int(await db.scalar(
        select(func.count(Proposal.id)).where(Proposal.contributor_id == user_id)
    ) or 0)
    activity = FactorResult(_saturating(proposals, Decimal("10")), proposals)
    return {"verification": verification, "framework_performance": framework_performance,
            "reviews_received": reviews_received, "attestations_received": attestations_received,
            "activity": activity}


async def operator_factors(db: AsyncSession, user_id: UUID, cfg: ReputationConfig) -> dict[str, FactorResult]:
    purchases = int(await db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.payer_id == user_id, Transaction.transaction_type == "purchase",
            Transaction.status == "completed",
        )
    ) or 0)
    purchase_activity = FactorResult(_saturating(purchases, Decimal("10")), purchases)

    active = int(await db.scalar(
        select(func.count(License.id)).where(License.operator_id == user_id, License.status == "active")
    ) or 0)
    revoked = int(await db.scalar(
        select(func.count(License.id)).where(License.operator_id == user_id, License.status == "revoked")
    ) or 0)
    total_lic = active + revoked
    compliance_val = Decimal("0.5") if total_lic == 0 else (Decimal(active) / Decimal(total_lic))
    license_compliance = FactorResult(compliance_val, total_lic)

    reviews_written = int(await db.scalar(
        select(func.count(Review.id)).where(Review.operator_id == user_id)
    ) or 0)
    review_quality = FactorResult(_saturating(reviews_written, Decimal("5")), reviews_written)

    # engagement: distinct projects created; disputes resolved against operator apply penalty.
    projects_created = int(await db.scalar(
        select(func.count(Project.id)).where(Project.operator_id == user_id)
    ) or 0)
    lost_disputes = int(await db.scalar(
        select(func.count(Dispute.id))
        .join(Project, Project.id == Dispute.project_id)
        .where(Project.operator_id == user_id, Dispute.status == "resolved",
               Dispute.resolution_type == "refund")
    ) or 0)
    eng_val = max(Decimal("0"), _saturating(projects_created, Decimal("5")) - cfg.dispute_penalty * Decimal(lost_disputes))
    engagement = FactorResult(eng_val, projects_created)
    return {"purchase_activity": purchase_activity, "license_compliance": license_compliance,
            "review_quality": review_quality, "engagement": engagement}
```

Before relying on column names, confirm each against the models: `Review.operator_id/score/framework_id`, `License.operator_id/framework_id/status`, `Transaction.payer_id/transaction_type/status`, `Attestation.target_type/target_id/outcome/status`, `Dispute.resolution_type/status/project_id`, `Proposal.contributor_id`, `Framework.contributor_id/status`, `UserRole.role/approved_at`, `User.kyc_status`. Grep each model file and fix any mismatch — these are the highest-risk lines in the plan. `License` is already verified to live in `app.modules.frameworks.models`.

- [ ] **Step 6: Write a DB-backed factor test (framework)**

`backend/tests/unit/modules/test_reputation_factors.py`:

```python
"""DB-backed factor aggregator smoke test for frameworks."""

import pytest

from app.modules.reputation import factors
from app.modules.reputation.weights import load_config


@pytest.mark.asyncio
async def test_framework_factors_reviews_and_adoption(db_session, framework_factory, review_factory, license_factory):
    fw = await framework_factory(status="published")
    await review_factory(framework_id=fw.id, score=5)
    await review_factory(framework_id=fw.id, score=4)
    await license_factory(framework_id=fw.id, status="active")
    cfg = await load_config(db_session, subject_type="framework")
    result = await factors.framework_factors(db_session, fw.id, cfg)
    assert result["reviews"].evidence == 2
    assert result["reviews"].value > 0
    assert result["adoption"].evidence == 1
```

Use existing factories if present (grep `backend/tests/factories`); if a needed factory is missing, build the rows inline with the ORM models instead of a factory.

- [ ] **Step 7: Run tests**

Run: `cd backend && uv run pytest tests/unit/modules/test_reputation_factors.py tests/unit/modules/test_reputation_engine.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/reputation/factors.py backend/app/modules/reputation/service.py backend/tests/unit/modules/test_reputation_engine.py backend/tests/unit/modules/test_reputation_factors.py
git commit -m "feat(reputation): factor aggregators + compute engine"
```

---

## Task 4: Recompute Beat task + single-subject recompute

**Files:**

- Modify: `backend/app/workers/tasks/reputation.py` (replace stub)
- Modify: `backend/app/workers/beat_schedule.py`
- Test: `backend/tests/unit/workers/test_reputation_tasks.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/workers/test_reputation_tasks.py`:

```python
"""recompute_reputation task tests (synchronous .apply())."""

import pytest

from app.modules.reputation import service as reputation_service
from app.workers.tasks.reputation import recompute_subject


@pytest.mark.asyncio
async def test_recompute_subject_upserts_and_is_idempotent(db_session, framework_factory, review_factory):
    fw = await framework_factory(status="published")
    for _ in range(4):
        await review_factory(framework_id=fw.id, score=5)
    await db_session.commit()

    await recompute_subject(subject_type="framework", subject_id=fw.id)
    first = await reputation_service.get_score(db_session, subject_type="framework", subject_id=fw.id)
    assert first is not None
    assert first.is_provisional is False  # 4 reviews ≥ min_activity 3
    await recompute_subject(subject_type="framework", subject_id=fw.id)
    second = await reputation_service.get_score(db_session, subject_type="framework", subject_id=fw.id)
    assert second.score == first.score
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/workers/test_reputation_tasks.py -v`
Expected: FAIL (`recompute_subject` missing).

- [ ] **Step 3: Implement the task module**

`backend/app/workers/tasks/reputation.py`:

```python
"""Reputation recompute Celery tasks (Phase 5e).

`recompute_reputation` (Beat, daily) recomputes every subject. `recompute_subject`
recomputes one subject and is reused by the admin manual trigger. Idempotent.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.reputation import factors
from app.modules.reputation import service as reputation_service
from app.modules.reputation.weights import load_config
from app.workers.async_runner import run_async
from app.workers.celery_app import app

_FACTOR_FN = {
    "framework": factors.framework_factors,
    "contributor": factors.contributor_factors,
    "operator": factors.operator_factors,
}


async def recompute_subject(*, subject_type: str, subject_id: UUID) -> None:
    """Recompute and upsert one subject's reputation in its own transaction."""
    async with async_session_factory() as db:
        async with db.begin():
            cfg = await load_config(db, subject_type=subject_type)
            factor_results = await _FACTOR_FN[subject_type](db, subject_id, cfg)
            result = reputation_service.combine_factors(cfg, factor_results)
            await reputation_service.upsert_score(
                db, subject_type=subject_type, subject_id=subject_id, result=result
            )


async def _recompute_all_impl() -> dict[str, int]:
    counts = {"framework": 0, "contributor": 0, "operator": 0}
    async with async_session_factory() as db:
        framework_ids = (await db.execute(
            select(Framework.id).where(Framework.status.in_(("published", "unpublished", "suspended")))
        )).scalars().all()
        # contributors + operators: any user holding the role
        from app.modules.auth.models import UserRole
        contributor_ids = (await db.execute(
            select(UserRole.user_id).where(UserRole.role == "contributor")
        )).scalars().all()
        operator_ids = (await db.execute(
            select(UserRole.user_id).where(UserRole.role == "operator")
        )).scalars().all()
    for fid in framework_ids:
        await recompute_subject(subject_type="framework", subject_id=fid)
        counts["framework"] += 1
    for cid in set(contributor_ids):
        await recompute_subject(subject_type="contributor", subject_id=cid)
        counts["contributor"] += 1
    for oid in set(operator_ids):
        await recompute_subject(subject_type="operator", subject_id=oid)
        counts["operator"] += 1
    return counts


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def recompute_reputation(self: Any) -> dict[str, int]:
    """Daily full reputation recompute."""
    log = logger.bind(module="reputation", action="recompute_reputation", task_id=self.request.id)
    log.info("task_started")
    try:
        result = run_async(_recompute_all_impl())
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=300) from exc
    log.info("task_completed", result=result)
    return result


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def recompute_subject_task(self: Any, subject_type: str, subject_id: str) -> dict[str, str]:
    """Queue-safe single-subject recompute used by the admin endpoint."""
    log = logger.bind(
        module="reputation",
        action="recompute_subject",
        task_id=self.request.id,
        subject_type=subject_type,
        subject_id=subject_id,
    )
    log.info("task_started")
    try:
        run_async(recompute_subject(subject_type=subject_type, subject_id=UUID(subject_id)))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=300) from exc
    log.info("task_completed")
    return {"status": "completed"}
```

Note: contributor framework_performance reads framework scores, so the full recompute does frameworks **before** contributors (order above is correct).

- [ ] **Step 4: Wire Beat schedule**

In `backend/app/workers/beat_schedule.py` add:

```python
    "recompute-reputation-daily": {
        "task": "app.workers.tasks.reputation.recompute_reputation",
        "schedule": 86400.0,
    },
```

Confirm `app.workers.tasks.reputation` is in the Celery `include`/autodiscover list (`app/workers/celery_app.py` already lists `app.workers.tasks.reputation` — verified).

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/workers/test_reputation_tasks.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/tasks/reputation.py backend/app/workers/beat_schedule.py backend/tests/unit/workers/test_reputation_tasks.py
git commit -m "feat(reputation): daily recompute Beat task + single-subject recompute"
```

---

## Task 5: Read API (framework/contributor public, operator gated) + admin recompute

**Files:**

- Create: `backend/app/modules/reputation/schemas.py`
- Create: `backend/app/modules/reputation/router.py`
- Modify: `backend/app/main.py` (mount router)
- Test: `backend/tests/integration/test_reputation_endpoints.py`

- [ ] **Step 1: Write the failing integration test**

`backend/tests/integration/test_reputation_endpoints.py`:

```python
"""Reputation read endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_public_framework_reputation_returns_headline_and_labels(
    async_client, framework_factory, review_factory, db_session
):
    fw = await framework_factory(status="published")
    for _ in range(4):
        await review_factory(framework_id=fw.id, score=5)
    await db_session.commit()
    from app.workers.tasks.reputation import recompute_subject
    await recompute_subject(subject_type="framework", subject_id=fw.id)

    resp = await async_client.get(f"/v1/reputation/framework/{fw.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert "score" in body and "factors" in body
    # labels only, never raw weights
    assert all("weight" not in f for f in body["factors"])


@pytest.mark.asyncio
async def test_operator_reputation_forbidden_to_stranger(async_client, user_factory, auth_headers):
    operator = await user_factory(roles=["operator"])
    stranger = await user_factory(roles=["contributor"])
    resp = await async_client.get(
        f"/v1/reputation/operator/{operator.id}",
        headers=auth_headers(stranger.id, ["contributor"]),
    )
    assert resp.status_code in (403, 404)
```

Match fixture names to `conftest.py`. In the current repo, replace `async_client` with the existing `client` fixture and build/authenticate users with the same helpers used by nearby auth-gated integration tests. If a contextual-membership fixture is needed for the positive operator case, defer that assertion to Task 6 where the Project-membership surface lands.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_reputation_endpoints.py -v`
Expected: FAIL (404 route not mounted).

- [ ] **Step 3: Implement schemas**

`backend/app/modules/reputation/schemas.py`:

```python
"""Reputation response schemas (headline + factor labels, no weights)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ReputationFactor(BaseModel):
    name: str
    label: str  # strong | moderate | weak


class ReputationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject_type: str
    subject_id: str
    score: Decimal | None
    is_provisional: bool
    factors: list[ReputationFactor]
    last_calculated_at: datetime | None


def to_response(row) -> "ReputationResponse":
    factors = [
        ReputationFactor(name=name, label=meta.get("label", "weak"))
        for name, meta in (row.components or {}).items()
    ]
    return ReputationResponse(
        subject_type=row.subject_type,
        subject_id=str(row.subject_id),
        score=None if row.is_provisional else row.score,
        is_provisional=row.is_provisional,
        factors=factors,
        last_calculated_at=row.last_calculated_at,
    )
```

Note: provisional subjects return `score=null` so the UI shows a "New" state (per design cold-start decision).

- [ ] **Step 4: Implement router**

`backend/app/modules/reputation/router.py`:

```python
"""Reputation read + admin recompute endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_current_user, require_role
from app.core.database import get_db  # match the actual dependency name used elsewhere
from app.modules.auth.models import User
from app.modules.reputation import service as reputation_service
from app.modules.reputation.schemas import ReputationResponse, to_response
router = APIRouter(prefix="/reputation", tags=["Reputation"])


async def _load_or_404(db, subject_type: str, subject_id: UUID):
    row = await reputation_service.get_score(db, subject_type=subject_type, subject_id=subject_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reputation not found.")
    return row


@router.get("/framework/{framework_id}", response_model=ReputationResponse)
async def get_framework_reputation(framework_id: UUID, db=Depends(get_db)) -> ReputationResponse:
    return to_response(await _load_or_404(db, "framework", framework_id))


@router.get("/contributor/{contributor_id}", response_model=ReputationResponse)
async def get_contributor_reputation(contributor_id: UUID, db=Depends(get_db)) -> ReputationResponse:
    return to_response(await _load_or_404(db, "contributor", contributor_id))


@router.get("/operator/{operator_id}", response_model=ReputationResponse)
async def get_operator_reputation(
    operator_id: UUID, db=Depends(get_db), user: User = Depends(get_current_user)
) -> ReputationResponse:
    """Operator reputation is contextual: self, an in-deal contributor, or admin."""
    is_admin = "admin" in {r.role for r in getattr(user, "roles", [])}
    if user.id != operator_id and not is_admin:
        # in-deal: the requester shares a Project with this operator
        shared = await _shares_project(db, contributor_id=user.id, operator_id=operator_id)
        if not shared:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")
    return to_response(await _load_or_404(db, "operator", operator_id))


async def _shares_project(db, *, contributor_id: UUID, operator_id: UUID) -> bool:
    from sqlalchemy import select
    from app.modules.projects.models import Project, Proposal
    row = await db.scalar(
        select(Project.id)
        .join(Proposal, Proposal.project_id == Project.id)
        .where(Project.operator_id == operator_id,
               Proposal.contributor_id == contributor_id,
               Proposal.status.in_(("pending", "accepted")))
        .limit(1)
    )
    return row is not None


@router.post("/admin/recompute/{subject_type}/{subject_id}", status_code=status.HTTP_202_ACCEPTED)
async def admin_recompute(
    subject_type: str, subject_id: UUID,
    admin: User = Depends(require_role("admin")),
) -> dict[str, str]:
    if subject_type not in ("framework", "contributor", "operator"):
        raise HTTPException(status_code=422, detail="Unsupported subject_type.")
    from app.workers.tasks.reputation import recompute_subject_task
    recompute_subject_task.delay(subject_type, str(subject_id))
    return {"status": "queued"}
```

Add a thin Celery task `recompute_subject_task(subject_type, subject_id)` in Task 4 wrapping `recompute_subject` (mirror the `@app.task` pattern used for `recompute_reputation`) and `.delay(...)` it here. Match `get_db` / `get_current_user` / `require_role` import paths to those used in `app/modules/explore/router.py` and `app/modules/admin/router.py`. Do not import unused membership helpers.

- [ ] **Step 5: Mount the router**

In `backend/app/main.py`, mirror existing `include_router` calls:

```python
from app.modules.reputation.router import router as reputation_router
application.include_router(reputation_router, prefix="/v1")
```

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_reputation_endpoints.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/reputation/schemas.py backend/app/modules/reputation/router.py backend/app/main.py backend/app/workers/tasks/reputation.py backend/tests/integration/test_reputation_endpoints.py
git commit -m "feat(reputation): read API + gated operator access + admin recompute"
```

---

## Task 6: Surface reputation in Explore + contributor profile + operator context

**Files:**

- Modify: `backend/app/modules/explore/schemas.py` (add `reputation` to `ExploreFrameworkCard` + contributor profile response)
- Modify: `backend/app/modules/explore/service.py` (batch-load framework + contributor reputation, attach)
- Modify: `backend/app/modules/projects/schemas.py` + `service.py` (attach operator reputation to proposal/project detail seen by the contributor)
- Test: extend `backend/tests/integration/test_explore_endpoints.py` + `test_projects_flow.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/integration/test_explore_endpoints.py`:

```python
@pytest.mark.asyncio
async def test_explore_card_includes_framework_reputation(
    async_client, framework_factory, review_factory, db_session
):
    fw = await framework_factory(status="published")
    for _ in range(4):
        await review_factory(framework_id=fw.id, score=5)
    await db_session.commit()
    from app.workers.tasks.reputation import recompute_subject
    await recompute_subject(subject_type="framework", subject_id=fw.id)

    resp = await async_client.get("/v1/explore/frameworks")
    assert resp.status_code == 200
    card = next(c for c in resp.json()["items"] if c["id"] == str(fw.id))
    assert "reputation" in card  # {score|null, is_provisional, factors:[...]}
```

Adjust the list path/response envelope (`items` vs other) to match the actual Explore list response.

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/integration/test_explore_endpoints.py -k reputation -v`
Expected: FAIL (`reputation` key absent).

- [ ] **Step 3: Add schema fields**

In `backend/app/modules/explore/schemas.py`, add an optional nested model and field on `ExploreFrameworkCard` and the contributor-profile response:

```python
class ExploreReputation(BaseModel):
    score: Decimal | None = None
    is_provisional: bool = True
    factors: list[dict] = Field(default_factory=list)  # [{name,label}]

# on ExploreFrameworkCard and the contributor profile response:
    reputation: ExploreReputation | None = None
```

- [ ] **Step 4: Batch-load + attach in service**

In `backend/app/modules/explore/service.py`, mirror the existing `_framework_attestation_badges` batch pattern: add `_framework_reputations(db, framework_ids) -> dict[UUID, ExploreReputation]` that selects `ReputationScore` rows where `subject_type='framework'` and `subject_id IN (...)`, maps to `ExploreReputation` (score=None when provisional). Attach in the same loop that attaches badges (around the card-build calls). Do the same for the contributor profile endpoint with `subject_type='contributor'`.

```python
from app.modules.reputation.models import ReputationScore

async def _framework_reputations(db, framework_ids):
    if not framework_ids:
        return {}
    rows = (await db.execute(
        select(ReputationScore).where(
            ReputationScore.subject_type == "framework",
            ReputationScore.subject_id.in_(framework_ids),
        )
    )).scalars()
    out = {}
    for r in rows:
        out[r.subject_id] = ExploreReputation(
            score=None if r.is_provisional else r.score,
            is_provisional=r.is_provisional,
            factors=[{"name": n, "label": m.get("label", "weak")} for n, m in (r.components or {}).items()],
        )
    return out
```

- [ ] **Step 5: Operator reputation on Project surfaces**

In `backend/app/modules/projects/schemas.py`, add optional `operator_reputation: ExploreReputation | None = None` (import or duplicate the small model) to the proposal/project-detail response the contributor sees. In `projects/service.py`, when the **accepted/bidding contributor** loads the project/proposal, load the operator's `ReputationScore` (`subject_type='operator'`) and attach. Do NOT attach it on any public/unauthenticated surface.

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_explore_endpoints.py tests/integration/test_projects_flow.py -k "reputation or operator" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/explore backend/app/modules/projects backend/tests/integration/test_explore_endpoints.py backend/tests/integration/test_projects_flow.py
git commit -m "feat(reputation): surface in Explore, contributor profile, operator context"
```

---

## Task 7: OpenAPI sync + frontend reputation component + E2E

**Files:**

- Modify: `contracts/openapi.yaml` (regen), `frontend/src/lib/generated/*` (codegen)
- Create: `frontend/src/components/modules/reputation/reputation-badge.tsx`
- Modify: Explore card + framework detail + contributor profile + project workspace components to render the badge
- Test: `frontend/tests/unit/components/reputation/reputation-badge.test.tsx`, `frontend/tests/e2e/reputation.spec.ts`

- [ ] **Step 1: Regenerate the contract + client**

Run the project's contract+codegen commands (match how prior phases did it — grep README/package.json/package scripts for the OpenAPI validation + `hey-api`/codegen script). Keep `contracts/openapi.yaml` as the source-of-truth contract, update it for the new endpoints/schemas, validate it, then regenerate `frontend/src/lib/generated/`.
Run: OpenAPI validator, then `corepack pnpm --dir frontend run <codegen-script>`.
Expected: `types.gen.ts` includes `ReputationResponse`/`ExploreReputation`.

- [ ] **Step 2: Write the failing component test**

`frontend/tests/unit/components/reputation/reputation-badge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";

describe("ReputationBadge", () => {
  it("shows New when provisional", () => {
    render(<ReputationBadge score={null} isProvisional factors={[]} />);
    expect(screen.getByText(/new/i)).toBeInTheDocument();
  });
  it("shows score and strong factor when present", () => {
    render(
      <ReputationBadge
        score={90}
        isProvisional={false}
        factors={[{ name: "attestations", label: "strong" }]}
      />,
    );
    expect(screen.getByText(/90/)).toBeInTheDocument();
    expect(screen.getByText(/attestations/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify fail**

Run: `corepack pnpm --dir frontend test reputation-badge`
Expected: FAIL (component missing).

- [ ] **Step 4: Implement the component (mobile-first)**

`frontend/src/components/modules/reputation/reputation-badge.tsx`:

```tsx
/**
 * Reputation badge — headline score + factor labels, or a "New" state when
 * provisional. Maps to Phase 5e (FR ReputationScore, full-spec §3234).
 */
interface ReputationFactor {
  name: string;
  label: "strong" | "moderate" | "weak";
}
interface Props {
  score: number | null;
  isProvisional: boolean;
  factors: ReputationFactor[];
}

export function ReputationBadge({ score, isProvisional, factors }: Props) {
  if (isProvisional || score === null) {
    return (
      <span className="inline-flex min-h-6 items-center rounded-[4px] border border-border bg-surface-subtle px-2 text-xs text-muted-foreground">
        New
      </span>
    );
  }
  const strong = factors.filter((f) => f.label === "strong").map((f) => f.name);
  return (
    <span className="inline-flex min-h-6 items-center gap-2 rounded-[4px] border border-success/30 bg-success/10 px-2 text-xs text-success">
      <span className="font-semibold">{Math.round(score)}</span>
      {strong.length > 0 && (
        <span className="text-success/80">· {strong.join(", ")}</span>
      )}
    </span>
  );
}
```

Render it on the Explore card, framework detail, contributor profile (`/explore/contributors/[id]`), and the Project workspace where the contributor sees the operator. Before writing UI code, invoke the repo `frontend-design` skill and adapt token names to the existing Tailwind/theme tokens if `bg-surface-subtle`, `text-success`, or `border-border` differ in this app. Test at 375px.

- [ ] **Step 5: Run component test**

Run: `corepack pnpm --dir frontend test reputation-badge`
Expected: PASS.

- [ ] **Step 6: E2E**

`frontend/tests/e2e/reputation.spec.ts`: seed a published framework with ≥3 reviews, trigger recompute (admin endpoint or direct task in test setup), load `/explore`, assert the card shows a numeric reputation; load a brand-new framework, assert "New". Match the existing E2E harness/auth setup in `frontend/tests/e2e/`.
Run: `corepack pnpm --dir frontend exec playwright test tests/e2e/reputation.spec.ts`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add contracts/openapi.yaml frontend/src/lib/generated frontend/src/components/modules/reputation frontend/tests
git commit -m "feat(reputation): openapi sync + reputation badge + e2e"
```

---

## Self-Review

**Spec coverage:** Decision 1 (pull-recompute) → Task 4. Decision 2 (3 subjects) → Task 3 factors. Decision 3 (0–100 weighted + config + daily) → Tasks 2/3/4. Decision 4 (provisional + neutral prior) → Task 3 `combine_factors` + provisional gating. Decision 5 (operator contextual) → Task 5 `_shares_project` + Task 6 Project surface. Decision 6 (fault-aware + decay + bounded) → Task 3 penalties (decay half-life is seeded + loaded; first cut applies penalty on rejected attestations / lost disputes — extend with explicit time-decay weighting in factors if richer decay is wanted). Decision 7 (headline + labels) → Task 5 schema (labels only, no weights) + Task 7 component. Decision 8 (no money) → no escrow/transaction writes anywhere.

**Known follow-up (not a gap, a scoped simplification):** `completion`/`recency` framework factors ship as explicit keys with `0.00` launch weight and neutral component values. They do not influence public framework reputation until real evidence-backed factors are implemented and the admin weight config is recalibrated.

**Placeholder scan:** no intentional executable placeholders remain. The Task 5 admin endpoint queues `recompute_subject_task`; do not ship a `501` stub.

**Type consistency:** `FactorResult`, `ScoreResult`, `ReputationConfig`, `combine_factors`, `upsert_score`, `get_score`, `recompute_subject`, `recompute_reputation` names are used consistently across Tasks 2–6. `ExploreReputation` reused in Tasks 6 (explore + projects).

**Highest-risk lines:** the factor SQL in Task 3 Step 5 — every source column must be verified against the real models before trusting it (the step says so explicitly). This is where the plan is most likely to need correction during execution.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/specs/2026-06-11-phase-5e-reputation-scoring.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
