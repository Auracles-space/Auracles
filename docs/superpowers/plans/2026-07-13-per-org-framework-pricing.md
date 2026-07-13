# Per-Organization Framework Pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a seller offer an `organizational` license tier at its own price (or reuse the single-user price), so a buyer purchasing on behalf of an organization is charged the org price.

**Architecture:** Add one nullable `frameworks.org_price` column. A single pure resolver (`resolve_license_price`) decides the charge for both purchase paths. Checkout couples buyer context to tier (self→single_user, org→organizational). The feature is invisible on frameworks that don't opt into the org tier.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, pytest; Next.js 15 App Router, Tailwind, hey-api generated client, vitest + React Testing Library, Playwright.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md`. Every task maps to it.
- Backend before frontend. OpenAPI updated before the frontend client is regenerated.
- TDD: one failing test → minimal code → green → commit. No horizontal slicing.
- `single_user` is a mandatory tier on every framework. `organizational` is optional.
- `org_price` is `NUMERIC(12,2)`, nullable. `NULL` + org tier present = "reuse base price". `NULL` + org tier absent = "not offered".
- Charge rule: `organizational` + `org_price` set → `org_price`; otherwise → `price`.
- Orphan `org_price` (set while `organizational` ∉ `license_types`) → 422. `org_price` may be less than `price`.
- `team` / `enterprise` tiers stay commented out / unsold. Collections + Partner API checkout untouched.
- Only USD (already enforced platform-wide).
- Commit directly on `main`. **No `Co-Authored-By` trailer** on any commit.
- Backend tests: `uv run pytest <path>`. Lint before claiming done: `uv run ruff check .` and `uv run mypy app` (run from `backend/`). Frontend: `npx vitest run <path>`, `npx tsc --noEmit`, `npx eslint <path>` (run from `frontend/`).
- Migration head is `2026_07_11_0079`. New migration chains from it.

---

## File Structure

**Backend**
- `backend/migrations/versions/2026_07_13_0080_framework_org_price.py` (create) — additive column + CHECK.
- `backend/app/modules/frameworks/models.py` (modify) — `org_price` column + CHECK constraint.
- `backend/app/modules/frameworks/schemas.py` (modify) — `PricingConfig.org_price` + `model_validator`.
- `backend/app/modules/frameworks/pricing.py` (create) — `resolve_license_price` pure helper.
- `backend/app/modules/frameworks/service.py` (modify) — persist `org_price` on create + edit, null-on-removal.
- `backend/app/modules/financials/service.py` (modify) — both purchase paths use the resolver.
- `backend/app/modules/explore/schemas.py` (modify) — `ExploreFrameworkDetail.org_price`.
- `backend/app/modules/explore/service.py` (modify) — serialize `org_price` in `get_detail`.
- `contracts/openapi.yaml` (modify) — reflect the new fields.

**Frontend**
- `frontend/src/lib/generated/*` (regenerate) — after OpenAPI update.
- `frontend/src/components/modules/frameworks/framework-form.tsx` (modify) — org tier option + `org_price` field.
- `frontend/src/app/(public)/explore/[id]/page.tsx` (modify) — conditional org-price line.
- `frontend/src/lib/marketplace/purchase-context.ts` (modify) — gate org buyers on org-tier availability.
- `frontend/src/components/modules/financials/checkout-form.tsx` (modify) — drop tier radios, derive tier from buyer.
- `frontend/tests/e2e/org-framework-pricing.spec.ts` (create) — seller enables org tier → org buys → charged org price.

**Test files**
- `backend/tests/unit/modules/test_framework_org_pricing.py` (create) — resolver + schema + service unit tests.
- `backend/tests/integration/test_org_purchase_pricing.py` (create) — charge-amount integration tests.
- `frontend/tests/unit/components/frameworks/framework-form-org-price.test.tsx` (create).
- `frontend/tests/unit/components/financials/checkout-org-tier.test.tsx` (create).
- `frontend/tests/unit/lib/purchase-context.test.ts` (create or extend).

---

### Task 1: Migration + model column + CHECK

**Files:**
- Create: `backend/migrations/versions/2026_07_13_0080_framework_org_price.py`
- Modify: `backend/app/modules/frameworks/models.py` (add column near `price` at line ~182; add CHECK in `__table_args__` near line ~99)
- Test: `backend/tests/unit/modules/test_framework_org_pricing.py`

**Interfaces:**
- Produces: `Framework.org_price: Mapped[Decimal | None]` (SQLAlchemy column); DB CHECK `ck_frameworks_org_price_positive`; migration revision `2026_07_13_0080`.

- [ ] **Step 1: Write the failing migration round-trip + column test**

Create `backend/tests/unit/modules/test_framework_org_pricing.py`:

```python
"""Unit tests for per-organization Framework pricing.

Covers the additive org_price column, PricingConfig validation, the
resolve_license_price helper, and service persistence rules. Maps to
docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _alembic_config() -> Config:
    """Build an Alembic config pointed at the backend migrations tree."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_migration_adds_org_price_column_and_downgrades() -> None:
    """org_price exists at head and the migration downgrades one step cleanly."""
    sync_engine = create_engine(app.state.settings.sync_database_url, pool_pre_ping=True)
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    columns = {c["name"] for c in inspect(sync_engine).get_columns("frameworks")}
    assert "org_price" in columns

    command.downgrade(cfg, "2026_07_11_0079")
    columns_after = {c["name"] for c in inspect(sync_engine).get_columns("frameworks")}
    assert "org_price" not in columns_after

    command.upgrade(cfg, "head")
    sync_engine.dispose()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/modules/test_framework_org_pricing.py::test_migration_adds_org_price_column_and_downgrades -v` (from `backend/`)
Expected: FAIL — `org_price` not in columns (column doesn't exist yet).

- [ ] **Step 3: Write the migration**

Create `backend/migrations/versions/2026_07_13_0080_framework_org_price.py`:

```python
"""Add frameworks.org_price for the organizational license pricing tier.

Additive, nullable column plus a positivity CHECK. NULL means the org tier is
either not offered or reuses the single-user price. Supports the per-org
pricing feature (docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md).

Revision ID: 2026_07_13_0080
Revises: 2026_07_11_0079
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_13_0080"
down_revision: str | Sequence[str] | None = "2026_07_11_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable org_price column and its positivity CHECK."""
    op.add_column(
        "frameworks",
        sa.Column("org_price", sa.Numeric(12, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_frameworks_org_price_positive",
        "frameworks",
        "org_price IS NULL OR org_price > 0",
    )


def downgrade() -> None:
    """Drop the org_price CHECK and column."""
    op.drop_constraint("ck_frameworks_org_price_positive", "frameworks", type_="check")
    op.drop_column("frameworks", "org_price")
```

- [ ] **Step 4: Add the ORM column + CHECK**

In `backend/app/modules/frameworks/models.py`, inside `Framework.__table_args__` add after the existing `ck_frameworks_price_positive` CheckConstraint:

```python
        CheckConstraint(
            "org_price IS NULL OR org_price > 0",
            name="ck_frameworks_org_price_positive",
        ),
```

And after the `price` column (line ~182) add:

```python
    org_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/modules/test_framework_org_pricing.py::test_migration_adds_org_price_column_and_downgrades -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/2026_07_13_0080_framework_org_price.py backend/app/modules/frameworks/models.py backend/tests/unit/modules/test_framework_org_pricing.py
git commit -m "Add frameworks.org_price column + migration for org pricing tier"
```

---

### Task 2: PricingConfig schema — org_price + validation

**Files:**
- Modify: `backend/app/modules/frameworks/schemas.py` (`PricingConfig`, line ~40)
- Test: `backend/tests/unit/modules/test_framework_org_pricing.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (schema-only).
- Produces: `PricingConfig.org_price: Decimal | None`; a `model_validator(mode="after")` enforcing single_user-mandatory and orphan-reject. `PricingConfig` is used for both request input and response building.

- [ ] **Step 1: Write the failing schema tests**

Append to `backend/tests/unit/modules/test_framework_org_pricing.py`:

```python
from pydantic import ValidationError

from app.modules.frameworks.schemas import PricingConfig


def test_pricing_config_accepts_org_tier_with_price() -> None:
    """Org tier plus an explicit org_price validates."""
    cfg = PricingConfig(
        price=Decimal("250.00"),
        license_types=["single_user", "organizational"],
        org_price=Decimal("900.00"),
    )
    assert cfg.org_price == Decimal("900.00")


def test_pricing_config_org_tier_without_price_means_reuse() -> None:
    """Org tier with org_price omitted is valid and left as None (reuse base)."""
    cfg = PricingConfig(
        price=Decimal("250.00"),
        license_types=["single_user", "organizational"],
    )
    assert cfg.org_price is None


def test_pricing_config_rejects_orphan_org_price() -> None:
    """org_price without the organizational tier is a 422-worthy error."""
    with pytest.raises(ValidationError):
        PricingConfig(
            price=Decimal("250.00"),
            license_types=["single_user"],
            org_price=Decimal("900.00"),
        )


def test_pricing_config_requires_single_user_tier() -> None:
    """single_user is mandatory on every framework."""
    with pytest.raises(ValidationError):
        PricingConfig(
            price=Decimal("250.00"),
            license_types=["organizational"],
            org_price=Decimal("900.00"),
        )


def test_pricing_config_allows_org_price_below_base() -> None:
    """A seller may price the org tier below the single-user price."""
    cfg = PricingConfig(
        price=Decimal("250.00"),
        license_types=["single_user", "organizational"],
        org_price=Decimal("100.00"),
    )
    assert cfg.org_price == Decimal("100.00")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/modules/test_framework_org_pricing.py -k pricing_config -v`
Expected: FAIL — `PricingConfig` has no `org_price` field (extra field ignored or the reuse test asserts a missing attribute).

- [ ] **Step 3: Add field + validator**

In `backend/app/modules/frameworks/schemas.py`, add `model_validator` to the imports (the file already imports `field_validator` from pydantic):

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```

(Adjust to the file's existing pydantic import line — keep the names already imported.)

In `PricingConfig`, add the field after `license_types` (line ~45):

```python
    org_price: Decimal | None = Field(
        default=None, gt=0, decimal_places=2, max_digits=12
    )
```

And add the validator (after the existing `currency_is_uppercase_iso_code`):

```python
    @model_validator(mode="after")
    def validate_org_pricing(self) -> "PricingConfig":
        """Enforce the single_user-mandatory and org_price-requires-org-tier rules.

        `single_user` must always be offered. An `org_price` is only meaningful
        when the `organizational` tier is on sale; a price without the tier is a
        seller error (BR: orphan org price).
        """
        if "single_user" not in self.license_types:
            raise ValueError("The single_user license tier is required.")
        if self.org_price is not None and "organizational" not in self.license_types:
            raise ValueError(
                "org_price requires the organizational license tier to be offered."
            )
        return self
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/modules/test_framework_org_pricing.py -k pricing_config -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/frameworks/schemas.py backend/tests/unit/modules/test_framework_org_pricing.py
git commit -m "Add org_price to PricingConfig with orphan-reject + single_user-mandatory validation"
```

---

### Task 3: Persist org_price on create + edit (null-on-removal)

**Files:**
- Modify: `backend/app/modules/frameworks/service.py` (`_apply_framework_pricing_update` ~line 411; the create path ~line 505; the response serializer `PricingConfig(...)` ~line 169)
- Test: `backend/tests/unit/modules/test_framework_org_pricing.py`

**Interfaces:**
- Consumes: `PricingConfig.org_price` (Task 2); `Framework.org_price` (Task 1).
- Produces: create + edit write `org_price`; edit nulls `org_price` when `organizational` leaves `license_types`; the framework response echoes `org_price` via `PricingConfig`.

- [ ] **Step 1: Write the failing service tests**

Append to `backend/tests/unit/modules/test_framework_org_pricing.py`:

```python
from app.modules.frameworks.models import Framework
from app.modules.frameworks.schemas import PricingConfig
from app.modules.frameworks.service import _apply_framework_pricing_update


def _framework(**kwargs) -> Framework:
    """Build an in-memory Framework with pricing defaults for unit assertions."""
    defaults = dict(
        price=Decimal("250.00"),
        currency="USD",
        license_types=["single_user"],
        org_price=None,
        commercial_rights=None,
        usage_restrictions=None,
    )
    defaults.update(kwargs)
    return Framework(**defaults)


def test_apply_pricing_sets_org_price() -> None:
    """Applying pricing with the org tier persists org_price."""
    fw = _framework()
    _apply_framework_pricing_update(
        fw,
        PricingConfig(
            price=Decimal("250.00"),
            license_types=["single_user", "organizational"],
            org_price=Decimal("900.00"),
        ),
    )
    assert fw.org_price == Decimal("900.00")
    assert fw.license_types == ["single_user", "organizational"]


def test_apply_pricing_nulls_org_price_when_tier_removed() -> None:
    """Removing the org tier on edit nulls org_price to keep the orphan invariant."""
    fw = _framework(
        license_types=["single_user", "organizational"],
        org_price=Decimal("900.00"),
    )
    _apply_framework_pricing_update(
        fw,
        PricingConfig(price=Decimal("250.00"), license_types=["single_user"]),
    )
    assert fw.org_price is None
    assert fw.license_types == ["single_user"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/modules/test_framework_org_pricing.py -k apply_pricing -v`
Expected: FAIL — `_apply_framework_pricing_update` doesn't set `org_price`.

- [ ] **Step 3: Update the service**

In `backend/app/modules/frameworks/service.py`, `_apply_framework_pricing_update` (line ~411), add the org_price line with the null-on-removal guard:

```python
def _apply_framework_pricing_update(
    framework: Framework,
    pricing: PricingConfig,
) -> None:
    """Apply pricing and licensing fields to a Framework row.

    When the organizational tier is not among the selected license types, any
    org_price is cleared so an orphan price can never persist (spec §7).
    """
    framework.price = pricing.price
    framework.currency = pricing.currency
    framework.license_types = list(pricing.license_types)
    framework.org_price = (
        pricing.org_price if "organizational" in pricing.license_types else None
    )
    framework.commercial_rights = pricing.commercial_rights
    framework.usage_restrictions = pricing.usage_restrictions
```

In the create path (line ~505, the `Framework(...)` constructor), add after `license_types=list(pricing.license_types),`:

```python
            org_price=(
                pricing.org_price
                if "organizational" in pricing.license_types
                else None
            ),
```

In the response serializer (line ~169, `pricing=PricingConfig(...)`), add `org_price=framework.org_price,` after `license_types=framework.license_types,`:

```python
        pricing=PricingConfig(
            price=framework.price,
            currency=framework.currency,
            license_types=framework.license_types,
            org_price=framework.org_price,
            commercial_rights=framework.commercial_rights,
            usage_restrictions=framework.usage_restrictions,
        ),
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/modules/test_framework_org_pricing.py -k apply_pricing -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/frameworks/service.py backend/tests/unit/modules/test_framework_org_pricing.py
git commit -m "Persist org_price on framework create/edit and null it when org tier removed"
```

---

### Task 4: `resolve_license_price` helper

**Files:**
- Create: `backend/app/modules/frameworks/pricing.py`
- Test: `backend/tests/unit/modules/test_framework_org_pricing.py`

**Interfaces:**
- Consumes: `Framework.org_price`, `Framework.price` (Task 1).
- Produces: `resolve_license_price(framework: Framework, license_type: str) -> Decimal`.

- [ ] **Step 1: Write the failing resolver tests**

Append to `backend/tests/unit/modules/test_framework_org_pricing.py`:

```python
from app.modules.frameworks.pricing import resolve_license_price


def test_resolve_price_single_user_uses_base() -> None:
    """single_user always charges the base price."""
    fw = _framework(org_price=Decimal("900.00"))
    assert resolve_license_price(fw, "single_user") == Decimal("250.00")


def test_resolve_price_org_uses_org_price_when_set() -> None:
    """organizational charges org_price when it is set."""
    fw = _framework(
        license_types=["single_user", "organizational"],
        org_price=Decimal("900.00"),
    )
    assert resolve_license_price(fw, "organizational") == Decimal("900.00")


def test_resolve_price_org_falls_back_to_base_on_reuse() -> None:
    """organizational with a NULL org_price reuses the base price."""
    fw = _framework(license_types=["single_user", "organizational"], org_price=None)
    assert resolve_license_price(fw, "organizational") == Decimal("250.00")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/modules/test_framework_org_pricing.py -k resolve_price -v`
Expected: FAIL — module `app.modules.frameworks.pricing` does not exist.

- [ ] **Step 3: Write the helper**

Create `backend/app/modules/frameworks/pricing.py`:

```python
"""Framework license price resolution.

Single source of truth for the charge amount of a license tier, shared by the
individual and organization purchase paths so commission, payout split, and
transaction amount all inherit the correct value.

Maps to docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md §5.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.frameworks.models import Framework


def resolve_license_price(framework: Framework, license_type: str) -> Decimal:
    """Return the charge amount for one license tier.

    The organizational tier falls back to the base price when `org_price` is
    NULL (the seller chose to reuse the single-user price). Every other tier
    charges the base price.

    Args:
        framework: The Framework being purchased.
        license_type: The requested license tier (e.g. "single_user",
            "organizational").

    Returns:
        The price to charge, as a Decimal.
    """
    if license_type == "organizational" and framework.org_price is not None:
        return framework.org_price
    return framework.price
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/modules/test_framework_org_pricing.py -k resolve_price -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/frameworks/pricing.py backend/tests/unit/modules/test_framework_org_pricing.py
git commit -m "Add resolve_license_price helper for per-tier charge resolution"
```

---

### Task 5: Wire resolver into both purchase paths

**Files:**
- Modify: `backend/app/modules/financials/service.py` (self path amount at line ~1095; org path amount at line ~1300; add import)
- Test: `backend/tests/integration/test_org_purchase_pricing.py`

**Interfaces:**
- Consumes: `resolve_license_price` (Task 4); `PurchaseRequest.license_type`.
- Produces: `Transaction.amount` equals the resolved tier price for both self and org purchases.

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/integration/test_org_purchase_pricing.py`. Follow the fixture pattern in `backend/tests/unit/modules/test_org_framework_purchase.py` (which already sets up an org with an active operator capability, a Stripe customer, a published framework, and a fake Stripe PaymentIntent). Reuse its `migrated_database` fixture and Stripe monkeypatching; adapt the framework to offer the org tier.

```python
"""Integration tests: org purchase charges the organizational tier price.

Verifies that create_org_framework_purchase stamps Transaction.amount from
resolve_license_price, not the flat base price. Maps to
docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md §5.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.financials import service as financials_service
from app.modules.financials.models import Transaction
from app.modules.financials.schemas import PurchaseRequest

# NOTE for implementer: import and reuse the org-purchase setup helpers/fixtures
# from tests/unit/modules/test_org_framework_purchase.py (org with active
# operator capability + Stripe customer, a published framework, fake Stripe
# PaymentIntent). Extend the framework factory in that setup to accept
# license_types and org_price so these two cases can be built.


@pytest.mark.asyncio
async def test_org_purchase_charges_org_price(org_pricing_state) -> None:
    """An org buying the organizational tier is charged org_price, not base."""
    ctx = org_pricing_state  # framework: price=250, org_price=900, org tier offered
    response = await financials_service.create_org_framework_purchase(
        ctx.db,
        org_id=ctx.org_id,
        actor=ctx.actor,
        framework_id=ctx.framework_id,
        payload=PurchaseRequest(license_type="organizational"),
    )
    txn = await ctx.db.get(Transaction, response.transaction_id)
    assert txn.amount == Decimal("900.00")


@pytest.mark.asyncio
async def test_org_purchase_reuse_charges_base_price(org_pricing_state_reuse) -> None:
    """An org tier with NULL org_price is charged the base price (reuse)."""
    ctx = org_pricing_state_reuse  # framework: price=250, org_price=None, org tier offered
    response = await financials_service.create_org_framework_purchase(
        ctx.db,
        org_id=ctx.org_id,
        actor=ctx.actor,
        framework_id=ctx.framework_id,
        payload=PurchaseRequest(license_type="organizational"),
    )
    txn = await ctx.db.get(Transaction, response.transaction_id)
    assert txn.amount == Decimal("250.00")
```

Build the `org_pricing_state` / `org_pricing_state_reuse` fixtures by copying the `org_purchase_state` fixture from `test_org_framework_purchase.py` and setting the framework's `license_types=["single_user", "organizational"]` with `org_price=Decimal("900.00")` (and `None` for the reuse fixture). Expose `db`, `org_id`, `actor`, `framework_id` on the yielded context object (a `SimpleNamespace`).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_org_purchase_pricing.py -v`
Expected: FAIL — `txn.amount` is `250.00` for the org-price case (resolver not wired; still charges base).

- [ ] **Step 3: Wire the resolver**

In `backend/app/modules/financials/service.py`, add the import near the other frameworks imports:

```python
from app.modules.frameworks.pricing import resolve_license_price
```

Replace **both** amount lines (self path ~1095 and org path ~1300):

```python
    amount = _normalise_money(framework.price)
```

with:

```python
    amount = _normalise_money(
        resolve_license_price(framework, payload.license_type)
    )
```

Both are preceded by the existing guard `if payload.license_type not in framework.license_types: raise HTTPException(422, ...)`, so an org tier can only be charged when the seller enabled it — leave that guard in place.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/integration/test_org_purchase_pricing.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Regression-check the existing purchase suites**

Run: `uv run pytest tests/unit/modules/test_org_framework_purchase.py tests/integration/test_financials_purchase_flow.py tests/integration/test_org_purchase_flow.py -q`
Expected: PASS — single-user purchases still charge the base price.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/financials/service.py backend/tests/integration/test_org_purchase_pricing.py
git commit -m "Charge resolved org-tier price in both framework purchase paths"
```

---

### Task 6: Explore detail schema + serializer + OpenAPI + client regen

**Files:**
- Modify: `backend/app/modules/explore/schemas.py` (`ExploreFrameworkDetail`, price/currency/license_types block ~line 89)
- Modify: `backend/app/modules/explore/service.py` (`get_detail`, ~line 1185 — where `ExploreFrameworkDetail(...)` is built)
- Modify: `contracts/openapi.yaml`
- Regenerate: `frontend/src/lib/generated/*`
- Test: `backend/tests/integration/test_explore_endpoints.py` (extend)

**Interfaces:**
- Consumes: `Framework.org_price` (Task 1).
- Produces: `ExploreFrameworkDetail.org_price: Decimal | None` on the public detail response; regenerated frontend type carries `org_price`.

- [ ] **Step 1: Write the failing detail test**

Add to `backend/tests/integration/test_explore_endpoints.py` (follow the existing detail-endpoint test pattern in that file for building a published framework and calling `GET /v1/explore/frameworks/{id}`):

```python
@pytest.mark.asyncio
async def test_framework_detail_exposes_org_price(published_org_tier_framework, client):
    """The public detail response includes org_price when the org tier is offered."""
    fw = published_org_tier_framework  # price=250, org_price=900, org tier offered
    response = await client.get(f"/v1/explore/frameworks/{fw.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["org_price"] == "900.00"
    assert "organizational" in body["license_types"]
```

Build `published_org_tier_framework` by extending the existing published-framework fixture in that test module to set `license_types=["single_user", "organizational"]` and `org_price=Decimal("900.00")`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_explore_endpoints.py -k org_price -v`
Expected: FAIL — response has no `org_price` key.

- [ ] **Step 3: Add the field + serialize it**

In `backend/app/modules/explore/schemas.py`, in `ExploreFrameworkDetail`, add after `license_types: list[str]` (line ~91):

```python
    org_price: Decimal | None = None
```

In `backend/app/modules/explore/service.py` `get_detail` (~line 1185), where `ExploreFrameworkDetail(...)` is constructed, add `org_price=framework.org_price,` alongside the existing `price=...`, `license_types=...` arguments.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/integration/test_explore_endpoints.py -k org_price -v`
Expected: PASS.

- [ ] **Step 5: Update OpenAPI + regenerate the client**

Regenerate `contracts/openapi.yaml` from the running app if the project generates it from FastAPI (check the repo's generation script); otherwise hand-edit `contracts/openapi.yaml` to add `org_price` (nullable number) to the `PricingConfig` and `ExploreFrameworkDetail` schemas. Then:

```bash
cd frontend && npm run generate:api
```

Verify `org_price` appears in the generated types:

```bash
grep -n "org_price" frontend/src/lib/generated/types.gen.ts
```
Expected: `org_price?: number | null` on the `PricingConfig` and `ExploreFrameworkDetail` types.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/explore/schemas.py backend/app/modules/explore/service.py contracts/openapi.yaml frontend/src/lib/generated backend/tests/integration/test_explore_endpoints.py
git commit -m "Expose org_price on framework detail response and regenerate client"
```

---

### Task 7: Creation/edit form — org tier + org_price field

**Files:**
- Modify: `frontend/src/components/modules/frameworks/framework-form.tsx` (license options ~line 39; form state ~line 100; submit payload ~line 229; license UI ~line 399)
- Test: `frontend/tests/unit/components/frameworks/framework-form-org-price.test.tsx`

**Interfaces:**
- Consumes: regenerated `PricingConfig` type with `org_price` (Task 6).
- Produces: form emits `org_price` in the pricing payload only when the `organizational` tier is selected.

- [ ] **Step 1: Write the failing component test**

Create `frontend/tests/unit/components/frameworks/framework-form-org-price.test.tsx`. Mirror the existing framework-form test setup (mock the sdk + form-client the same way other org tests do). Assert:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Mock generated sdk + form-client per the repo's existing framework-form tests.

import { FrameworkForm } from "@/components/modules/frameworks/framework-form";

describe("FrameworkForm org pricing tier", () => {
  it("reveals the org price field only when the organizational tier is selected", () => {
    render(<FrameworkForm /* required props per existing tests */ />);
    expect(screen.queryByLabelText(/Organization price/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/^Organizational$/i));
    expect(screen.getByLabelText(/Organization price/i)).toBeInTheDocument();
  });
});
```

(Fill the required `FrameworkForm` props by copying an existing render call from the current framework-form test file. If none exists, construct minimal props from the component's `FrameworkFormProps` type.)

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/unit/components/frameworks/framework-form-org-price.test.tsx` (from `frontend/`)
Expected: FAIL — no "Organizational" checkbox / no org-price field.

- [ ] **Step 3: Implement the form changes**

In `frontend/src/components/modules/frameworks/framework-form.tsx`:

1. Uncomment the `organizational` option in `LICENSE_TYPE_OPTIONS` (leave `team`/`enterprise` commented):

```tsx
    { value: "single_user", label: "Single user" },
    { value: "organizational", label: "Organizational" },
    // { value: "team", label: "Team" },
    // { value: "enterprise", label: "Enterprise" },
```

2. Add `orgPrice` to the form state type + initial state (near `price`):

```tsx
    orgPrice: framework?.pricing.org_price != null ? String(framework.pricing.org_price) : "",
```

3. Keep `single_user` non-removable: in `toggleLicenseType`, prevent unchecking `single_user` (guard: if `value === "single_user"` and it is currently checked, no-op).

4. Render the org-price input conditionally, right after the license-types block (~line 428), only when `form.licenseTypes.includes("organizational")`:

```tsx
{form.licenseTypes.includes("organizational") && (
  <div>
    <label htmlFor="org_price" className="mb-1 block text-sm font-semibold text-foreground">
      Organization price
    </label>
    <Input
      id="org_price"
      inputMode="decimal"
      value={form.orgPrice}
      onChange={(event) =>
        setForm((current) => ({ ...current, orgPrice: sanitizePriceInput(event.target.value) }))
      }
      placeholder="Same as single-user price"
    />
    <p className="mt-1 text-xs text-foreground-muted">
      Leave blank to charge the same as the single-user price.
    </p>
  </div>
)}
```

5. In the submit builder (~line 229) include `org_price` only when the org tier is selected and a value was entered:

```tsx
      org_price:
        form.licenseTypes.includes("organizational") && form.orgPrice.trim() !== ""
          ? form.orgPrice
          : null,
```

(Match the payload's existing typing — `price` is sent as a string today; send `org_price` the same way, or `null`.)

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/unit/components/frameworks/framework-form-org-price.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint + commit**

```bash
cd frontend && npx tsc --noEmit && npx eslint src/components/modules/frameworks/framework-form.tsx
git add frontend/src/components/modules/frameworks/framework-form.tsx frontend/tests/unit/components/frameworks/framework-form-org-price.test.tsx
git commit -m "Add organizational license tier + org price field to framework form"
```

---

### Task 8: Framework detail — conditional org-price line

**Files:**
- Modify: `frontend/src/app/(public)/explore/[id]/page.tsx` (price block ~line 99)
- Test: covered by e2e (Task 10) + a light render assertion here if the page is componentized; otherwise verify visually.

**Interfaces:**
- Consumes: `framework.org_price`, `framework.license_types` on the detail response (Task 6).
- Produces: a second price line under "Starting price" when the org tier is offered.

- [ ] **Step 1: Implement the conditional line**

In `frontend/src/app/(public)/explore/[id]/page.tsx`, after the existing "Starting price" block (~line 99–102), add:

```tsx
{framework.license_types.includes("organizational") && (
  <div className="mt-3">
    <p className="text-sm text-foreground-muted">Organizational</p>
    <p className="text-lg font-semibold text-foreground">
      {framework.org_price != null
        ? formatMoney(framework.org_price, framework.currency)
        : `${formatMoney(framework.price, framework.currency)} — same as single user`}
    </p>
  </div>
)}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0 (the regenerated type carries `org_price`).

- [ ] **Step 3: Verify at 375px**

Load a framework that offers the org tier; confirm the "Organizational" line renders under "Starting price" without horizontal overflow on a 375px viewport, and is absent on a single-user-only framework.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/(public)/explore/[id]/page.tsx"
git commit -m "Show organizational price line on framework detail when the tier is offered"
```

---

### Task 9: Checkout — buyer-derived tier, drop radios, gate org buyers

**Files:**
- Modify: `frontend/src/lib/marketplace/purchase-context.ts` (`eligibleOrgBuyers`, `buyerOptions`)
- Modify: `frontend/src/components/modules/financials/checkout-form.tsx` (buyer + license selection; price display)
- Test: `frontend/tests/unit/lib/purchase-context.test.ts`, `frontend/tests/unit/components/financials/checkout-org-tier.test.tsx`

**Interfaces:**
- Consumes: `framework.license_types`, `framework.org_price` (Task 6); `eligibleOrgBuyers`/`buyerOptions` gain an `offersOrgTier: boolean` argument.
- Produces: org buyers listed only when the framework offers the org tier; the derived `license_type` sent to `startPurchase` is `organizational` for org buyers and `single_user` for self.

- [ ] **Step 1: Write the failing purchase-context test**

Create/extend `frontend/tests/unit/lib/purchase-context.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { buyerOptions, eligibleOrgBuyers } from "@/lib/marketplace/purchase-context";

const eligibleOrg = {
  org: { id: "org-1", name: "Acme", slug: "acme", country: "US" },
  role: "owner",
  capabilities: { operator: "active" },
} as never;

describe("purchase-context org-tier gating", () => {
  it("lists no org buyers when the framework does not offer the org tier", () => {
    expect(eligibleOrgBuyers([eligibleOrg], false)).toHaveLength(0);
  });

  it("lists an eligible org buyer when the framework offers the org tier", () => {
    const opts = eligibleOrgBuyers([eligibleOrg], true);
    expect(opts).toEqual([{ kind: "org", orgId: "org-1", label: "Acme" }]);
  });

  it("buyerOptions always starts with self", () => {
    expect(buyerOptions([eligibleOrg], false)[0]).toEqual({ kind: "self", label: "Myself" });
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/unit/lib/purchase-context.test.ts`
Expected: FAIL — `eligibleOrgBuyers` takes one argument; the `false` gate is ignored.

- [ ] **Step 3: Add the org-tier gate**

In `frontend/src/lib/marketplace/purchase-context.ts`:

```ts
/** Orgs the caller may purchase on behalf of, only when the framework offers the org tier. */
export function eligibleOrgBuyers(
  orgs: MyOrganizationResponse[],
  offersOrgTier: boolean,
): BuyerOption[] {
  if (!offersOrgTier) return [];
  return orgs
    .filter((o) => (o.role === "admin" || o.role === "owner") && o.capabilities?.operator === "active")
    .map((o) => ({ kind: "org", orgId: o.org.id, label: o.org.name }));
}

/** Self option followed by eligible org buyers (org buyers gated on org-tier availability). */
export function buyerOptions(
  orgs: MyOrganizationResponse[],
  offersOrgTier: boolean,
): BuyerOption[] {
  return [{ kind: "self", label: "Myself" }, ...eligibleOrgBuyers(orgs, offersOrgTier)];
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/unit/lib/purchase-context.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the failing checkout component test**

Create `frontend/tests/unit/components/financials/checkout-org-tier.test.tsx`. Mock the sdk (`listMyOrganizationsV1OrgsMineGet` returns one eligible org) and `startPurchase`. Assert two behaviors:

```tsx
// 1. For a single-user-only framework, no buyer selector renders and license
//    radios are gone — only a self checkout button.
// 2. For an org-tier framework with an eligible org, selecting the org buyer
//    displays the org price and startPurchase is called with licenseType
//    "organizational".
```

Model the test on the existing checkout-form test in the repo (same Stripe/client mocks). Use a framework prop with `license_types: ["single_user", "organizational"]`, `price: "250.00"`, `org_price: "900.00"`.

- [ ] **Step 6: Run to verify failure**

Run: `npx vitest run tests/unit/components/financials/checkout-org-tier.test.tsx`
Expected: FAIL — license radios still render; tier not derived from buyer.

- [ ] **Step 7: Rework checkout-form**

In `frontend/src/components/modules/financials/checkout-form.tsx`:

1. Pass the org-tier flag when building buyers:

```tsx
const offersOrgTier = framework.license_types.includes("organizational");
// ...
const opts = buyerOptions(result.data.organizations, offersOrgTier);
```

2. **Remove the license-type radio group** and the `licenseType`/`availableLicenses` state. Derive the tier from the selected buyer:

```tsx
const licenseType = buyer.kind === "org" ? "organizational" : "single_user";
```

3. Compute the displayed price from the buyer:

```tsx
const displayPrice =
  buyer.kind === "org" && framework.org_price != null
    ? framework.org_price
    : framework.price;
```

Render `formatMoney(displayPrice, framework.currency)` in the price line (replacing the per-radio price). When `buyer.kind === "org"` and `framework.org_price == null`, append the "— same as single user" hint.

4. Pass the derived `licenseType` to `startPurchase({ buyer, frameworkId, licenseType, headers })` — unchanged call shape.

5. The buyer selector still renders only when `buyers.length > 1` (existing behavior) — so a single-user-only framework (no org buyers) renders exactly as today.

- [ ] **Step 8: Run to verify pass**

Run: `npx vitest run tests/unit/components/financials/checkout-org-tier.test.tsx`
Expected: PASS.

- [ ] **Step 9: Typecheck + lint + commit**

```bash
cd frontend && npx tsc --noEmit && npx eslint src/lib/marketplace/purchase-context.ts src/components/modules/financials/checkout-form.tsx
git add frontend/src/lib/marketplace/purchase-context.ts frontend/src/components/modules/financials/checkout-form.tsx frontend/tests/unit/lib/purchase-context.test.ts frontend/tests/unit/components/financials/checkout-org-tier.test.tsx
git commit -m "Couple checkout tier to buyer context and gate org buyers on org-tier availability"
```

---

### Task 10: E2E — seller enables org tier → org buys → charged org price

**Files:**
- Create: `frontend/tests/e2e/org-framework-pricing.spec.ts`

**Interfaces:**
- Consumes: the whole feature.

- [ ] **Step 1: Write the mocked-route e2e**

Create `frontend/tests/e2e/org-framework-pricing.spec.ts` modeled on the existing mocked-route e2e in `frontend/tests/e2e/` (e.g. `become-attestor.spec.ts` — reuse its session-hint cookie + mocked `/v1/orgs` route helpers). At a 375px viewport:

1. Seed an authenticated operator with one eligible org (owner + `capabilities.operator = "active"`).
2. Mock the framework detail route to return `license_types: ["single_user", "organizational"]`, `price: "250.00"`, `org_price: "900.00"`.
3. Mock `POST /v1/orgs/{org_id}/frameworks/{framework_id}/purchase` to capture the request and return a fake `client_secret` + `transaction_id`.
4. Navigate to the framework detail, assert the "Organizational — $900.00" line renders.
5. Open checkout, select the org buyer, assert the displayed price is `$900.00`, submit, and assert the org-purchase route was called (not the self route).

- [ ] **Step 2: Run it**

Run: `npx playwright test tests/e2e/org-framework-pricing.spec.ts`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/org-framework-pricing.spec.ts
git commit -m "E2E: org buyer is charged the organizational tier price"
```

---

## Final verification (after all tasks)

- [ ] Backend: `cd backend && uv run pytest tests/unit/modules/test_framework_org_pricing.py tests/integration/test_org_purchase_pricing.py tests/integration/test_explore_endpoints.py -q`
- [ ] Backend lint/type (whole repo): `cd backend && uv run ruff check . && uv run mypy app`
- [ ] Migration round-trip: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- [ ] Frontend: `cd frontend && npx vitest run && npx tsc --noEmit && npx eslint .`
- [ ] Manual 375px pass: framework with org tier shows the org-price line + org checkout price; single-user-only framework is unchanged.

---

## Self-Review

**Spec coverage:**
- §4 schema → Task 1. §4 tier switch semantics → Task 2 (validation) + Task 3 (persistence).
- §5 resolver → Task 4; wired → Task 5.
- §6 coupled checkout + org-buyer gate → Task 9.
- §7 validation (orphan-reject, positivity, below-base allowed, edit null-on-removal) → Task 2 + Task 3.
- §8 display (card unchanged, detail line, checkout price) → Task 8 (detail) + Task 9 (checkout). Card intentionally untouched.
- §9 API contract → Task 6.
- §10 creation form → Task 7.
- §12 testing → tests embedded per task; §13 migration round-trip → Task 1 + final verification.

**Type consistency:** `resolve_license_price(framework, license_type) -> Decimal` (Task 4) used verbatim in Task 5. `PricingConfig.org_price` (Task 2) read in Task 3 and serialized in Task 3/6. `eligibleOrgBuyers(orgs, offersOrgTier)` / `buyerOptions(orgs, offersOrgTier)` (Task 9) consistent across their test and consumer. `org_price` field name identical across model, schema, explore schema, and generated client.

**No placeholders:** every code step shows complete code. Two frontend test bodies (Task 9 Step 5, Task 10) describe assertions in prose because they depend on the repo's existing checkout/e2e mock scaffolding; the implementer is directed to the concrete file to copy from (`checkout-form` test, `become-attestor.spec.ts`).
