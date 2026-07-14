# Taxonomy Unification + AMM Field-Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make attestor specialisation share one canonical controlled vocabulary with framework tagging, and repoint the AMM matcher at the correct framework fields so framework-target matching actually scores and gates correctly.

**Architecture:** Promote the framework taxonomy to a shared module (`app/shared/taxonomy.py`) that both `frameworks` and attestor code import. Rename the attestor `framework_categories` field to `functions`, adopt canonical `sector`/`function`/`jurisdiction` values, and fix `scoring`/`matching_service` to derive sector, function, and jurisdiction from the framework itself for framework targets. One Alembic migration renames the column and remaps existing data.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Alembic, pytest/httpx AsyncClient (backend); Next.js 15 App Router, Tailwind, vitest + Testing Library, hey-api generated client (frontend).

## Global Constraints

- Work directly on `main`. Do not create branches. (Ask before any branch.)
- Commit messages end at the last meaningful line — **no `Co-Authored-By` trailer**.
- TDD RED→GREEN per behavior: write the failing test, watch it fail, implement, watch it pass, commit.
- Backend precedes frontend. OpenAPI-first: update `contracts/openapi.yaml` (by dumping `app.openapi()`) before regenerating the frontend client.
- Backend commands run through `uv run` from `backend/`. Test DB is `auracles_test`; integration tests use the `migrated_database` fixture (runs Alembic), so **model/column renames and their migration must land in the same task** or integration tests fail.
- Full-repo lint before claiming a task clean: `uv run ruff check .` and `uv run mypy app` (backend); `npx tsc --noEmit` and `npx eslint <files>` (frontend). Frontend is **npm**, not pnpm.
- Canonical values are snake_case slugs. Attestor writes must reject off-vocabulary values with 422.
- Alembic: `alembic upgrade head` and `alembic downgrade -1` must both succeed. New revision `down_revision = "2026_07_13_0081"` (current head).
- Never drop attestor data during migration: unmapped values are left as-is and logged.

**Canonical value sets (use verbatim):**

- SECTORS (12): `private_equity`, `venture_capital`, `infrastructure`, `real_estate`, `healthcare`, `manufacturing`, `government`, `education`, `financial_services`, `energy`, `telecommunications`, `technology`
- FUNCTIONS (14): `governance`, `compliance`, `risk_management`, `operations`, `finance`, `legal`, `engineering`, `human_resources`, `sales`, `marketing`, `product`, `data_ai`, `information_security`, `investment_management`
- CATEGORIES (10, doc types): `framework`, `playbook`, `sop`, `policy`, `template`, `toolkit`, `assessment`, `control_matrix`, `workflow`, `training_program`
- INDUSTRIES (14): `fund_management`, `portfolio_operations`, `energy_infrastructure`, `transportation_infrastructure`, `residential_real_estate`, `commercial_real_estate`, `property_management`, `healthcare_providers`, `health_technology`, `medical_devices`, `software_engineering`, `data_centers`, `renewable_energy`, `public_sector_agencies`
- JURISDICTIONS (24 slugs): `global`, `european_union`, `australia`, `brazil`, `canada`, `china`, `france`, `germany`, `hong_kong`, `india`, `ireland`, `japan`, `kenya`, `mexico`, `netherlands`, `new_zealand`, `nigeria`, `saudi_arabia`, `singapore`, `south_africa`, `switzerland`, `united_arab_emirates`, `united_kingdom`, `united_states`

**Migration mappings (old attestor vocab → canonical):**

- Sectors: `PE`→`private_equity`, `VC`→`venture_capital`, `Infrastructure`→`infrastructure`, `Real Estate`→`real_estate`
- Functions (was `framework_categories`): `Compliance`→`compliance`, `Governance`→`governance`, `Risk`→`risk_management`, `Operations`→`operations`, `Legal`→`legal`, `Finance`→`finance`, `HR`→`human_resources`, `Technology`→`engineering`, `Investment Management`→`investment_management`
- Jurisdictions (best-effort): `United States`→`united_states`, `United Kingdom`→`united_kingdom`, `Nigeria`→`nigeria`, `Global`→`global`, `European Union`→`european_union`, `Canada`→`canada`, `Germany`→`germany`, `France`→`france`, `Singapore`→`singapore`, `South Africa`→`south_africa`, `Japan`→`japan`, `India`→`india`, `Ireland`→`ireland`, `Netherlands`→`netherlands`, `Switzerland`→`switzerland`, `Australia`→`australia`, `Brazil`→`brazil`, `China`→`china`, `Hong Kong`→`hong_kong`, `Kenya`→`kenya`, `Mexico`→`mexico`, `New Zealand`→`new_zealand`, `Saudi Arabia`→`saudi_arabia`, `United Arab Emirates`→`united_arab_emirates`

---

## File Structure

**Create:**
- `backend/app/shared/taxonomy.py` — canonical vocabulary + validators (single source of truth).
- `backend/migrations/versions/2026_07_14_0082_unify_attestor_taxonomy.py` — column rename + data remap.
- `backend/tests/unit/test_shared_taxonomy.py` — validator + membership tests.

**Modify (backend):**
- `backend/app/modules/frameworks/taxonomy.py` — re-export Literals from shared module.
- `backend/app/modules/attestation/taxonomy.py` — **delete**.
- `backend/app/modules/organizations/models.py` — rename `framework_categories`→`functions` (both attestor tables).
- `backend/app/modules/organizations/schemas.py` — rename field, swap validators, bump `max_length`.
- `backend/app/modules/organizations/attestor_application_service.py` — rename references.
- `backend/app/modules/organizations/router.py:157` — rename reference.
- `backend/app/modules/attestation/scoring.py` — `category_match`→`function_match`, weight key.
- `backend/app/modules/attestation/matching_service.py` — framework-derived sector/function/jurisdiction + hard-filter refactor.
- `backend/app/modules/attestation/directory_service.py` — rename filter param + field.
- `backend/app/modules/attestation/schemas.py` — directory field rename; request-schema relax.
- `backend/app/modules/attestation/router.py:216,224` — directory query-param rename.
- `backend/app/modules/attestation/service.py` — request create passes through relaxed fields.

**Modify (frontend):**
- `frontend/src/lib/marketplace/taxonomy.ts` — add `investment_management` to `FUNCTION_OPTIONS`.
- `frontend/src/components/modules/organizations/attestor/apply-gate.tsx` — canonical options, `functions` field.
- `frontend/src/components/modules/organizations/attestor/apply-gate.test.tsx` — update expectations.
- `frontend/src/components/modules/attestation/requestor-panel.tsx` — hide specializations for framework targets.
- `frontend/src/lib/generated/{sdk.gen.ts,types.gen.ts}` — regenerated.
- `contracts/openapi.yaml` — regenerated.

---

### Task 1: Shared canonical taxonomy module

**Files:**
- Create: `backend/app/shared/taxonomy.py`
- Create: `backend/tests/unit/test_shared_taxonomy.py`
- Modify: `backend/app/modules/frameworks/taxonomy.py`

**Interfaces:**
- Produces: `SECTORS`, `FUNCTIONS`, `CATEGORIES`, `INDUSTRIES`, `JURISDICTIONS` (`frozenset[str]`); `FrameworkSector`, `FrameworkFunction`, `FrameworkCategory`, `FrameworkIndustry` (`Literal` types); `validate_sectors(list[str]) -> list[str]`, `validate_functions(list[str]) -> list[str]`, `validate_jurisdictions(list[str]) -> list[str]` (trim, de-dupe first-seen, reject unknown, require ≥1).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_shared_taxonomy.py`:

```python
"""Unit tests for the canonical shared taxonomy and its validators."""

from __future__ import annotations

import pytest

from app.shared import taxonomy


def test_functions_includes_investment_management():
    """investment_management is a first-class canonical function."""
    assert "investment_management" in taxonomy.FUNCTIONS


def test_sectors_are_canonical_slugs():
    """Sector set uses the framework snake_case slugs, not attestor labels."""
    assert "private_equity" in taxonomy.SECTORS
    assert "PE" not in taxonomy.SECTORS


def test_validate_functions_accepts_canonical_and_dedupes():
    """Known values pass; duplicates collapse first-seen; order preserved."""
    assert taxonomy.validate_functions(["compliance", "risk_management", "compliance"]) == [
        "compliance",
        "risk_management",
    ]


def test_validate_functions_rejects_unknown():
    """An off-vocabulary function raises ValueError."""
    with pytest.raises(ValueError, match="not a valid function"):
        taxonomy.validate_functions(["Compliance"])


def test_validate_sectors_requires_at_least_one():
    """An empty list is rejected."""
    with pytest.raises(ValueError, match="at least one sector"):
        taxonomy.validate_sectors([])


def test_validate_jurisdictions_accepts_slug():
    """Jurisdiction slugs validate against the canonical set."""
    assert taxonomy.validate_jurisdictions(["united_states", "nigeria"]) == [
        "united_states",
        "nigeria",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_shared_taxonomy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.shared.taxonomy'`.

- [ ] **Step 3: Create the shared taxonomy module**

Create `backend/app/shared/taxonomy.py`:

```python
"""Canonical controlled taxonomy shared across marketplace subsystems.

Single source of truth for the Sector, Function, Category, Industry, and
Jurisdiction vocabularies used by Framework write APIs, Explore filters, and
Attestor specialisation + AMM matching. Framework and Attestor code both import
from here so the matcher can compare an attestor's expertise against a
framework's own tags on identical values.
"""

from __future__ import annotations

from typing import Literal, get_args

FrameworkCategory = Literal[
    "framework",
    "playbook",
    "sop",
    "policy",
    "template",
    "toolkit",
    "assessment",
    "control_matrix",
    "workflow",
    "training_program",
]

FrameworkSector = Literal[
    "private_equity",
    "venture_capital",
    "infrastructure",
    "real_estate",
    "healthcare",
    "manufacturing",
    "government",
    "education",
    "financial_services",
    "energy",
    "telecommunications",
    "technology",
]

FrameworkIndustry = Literal[
    "fund_management",
    "portfolio_operations",
    "energy_infrastructure",
    "transportation_infrastructure",
    "residential_real_estate",
    "commercial_real_estate",
    "property_management",
    "healthcare_providers",
    "health_technology",
    "medical_devices",
    "software_engineering",
    "data_centers",
    "renewable_energy",
    "public_sector_agencies",
]

FrameworkFunction = Literal[
    "governance",
    "compliance",
    "risk_management",
    "operations",
    "finance",
    "legal",
    "engineering",
    "human_resources",
    "sales",
    "marketing",
    "product",
    "data_ai",
    "information_security",
    "investment_management",
]

CATEGORIES: frozenset[str] = frozenset(get_args(FrameworkCategory))
SECTORS: frozenset[str] = frozenset(get_args(FrameworkSector))
INDUSTRIES: frozenset[str] = frozenset(get_args(FrameworkIndustry))
FUNCTIONS: frozenset[str] = frozenset(get_args(FrameworkFunction))

JURISDICTIONS: frozenset[str] = frozenset(
    {
        "global",
        "european_union",
        "australia",
        "brazil",
        "canada",
        "china",
        "france",
        "germany",
        "hong_kong",
        "india",
        "ireland",
        "japan",
        "kenya",
        "mexico",
        "netherlands",
        "new_zealand",
        "nigeria",
        "saudi_arabia",
        "singapore",
        "south_africa",
        "switzerland",
        "united_arab_emirates",
        "united_kingdom",
        "united_states",
    }
)


def _validate(values: list[str], allowed: frozenset[str], label: str) -> list[str]:
    """Trim, de-duplicate (first-seen), and reject values outside ``allowed``.

    Args:
        values: Raw submitted values.
        allowed: The controlled set the values must belong to.
        label: Human-readable singular noun for error messages.

    Returns:
        The cleaned, de-duplicated, order-preserving list.

    Raises:
        ValueError: If any value is unknown, or the result is empty.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if item not in allowed:
            raise ValueError(f"{item!r} is not a valid {label}.")
        if item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    if not cleaned:
        raise ValueError(f"at least one {label} is required.")
    return cleaned


def validate_sectors(values: list[str]) -> list[str]:
    """Validate sector slugs against the canonical set."""
    return _validate(values, SECTORS, "sector")


def validate_functions(values: list[str]) -> list[str]:
    """Validate function slugs against the canonical set."""
    return _validate(values, FUNCTIONS, "function")


def validate_jurisdictions(values: list[str]) -> list[str]:
    """Validate jurisdiction slugs against the canonical set."""
    return _validate(values, JURISDICTIONS, "jurisdiction")
```

- [ ] **Step 4: Point `frameworks/taxonomy.py` at the shared module**

Replace the entire body of `backend/app/modules/frameworks/taxonomy.py` with a re-export so framework write APIs keep the same import path:

```python
"""Canonical Framework taxonomy values accepted by contributor write APIs.

Re-exports the shared marketplace taxonomy so Framework write schemas and the
Attestor matcher validate against one identical vocabulary.
"""

from __future__ import annotations

from app.shared.taxonomy import (
    FrameworkCategory,
    FrameworkFunction,
    FrameworkIndustry,
    FrameworkSector,
)

__all__ = [
    "FrameworkCategory",
    "FrameworkFunction",
    "FrameworkIndustry",
    "FrameworkSector",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_shared_taxonomy.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Verify framework writes still accept the enum (incl. new value)**

Run: `cd backend && uv run pytest tests/integration/test_frameworks_endpoints.py -q`
Expected: PASS (existing framework write tests unaffected by the re-export).

- [ ] **Step 7: Lint + commit**

```bash
cd backend
uv run ruff check . && uv run mypy app
git add app/shared/taxonomy.py app/modules/frameworks/taxonomy.py tests/unit/test_shared_taxonomy.py
git commit -m "Add shared canonical taxonomy with investment_management function"
```

---

### Task 2: Rename attestor `framework_categories` → `functions`, adopt canonical validators, migrate data

This is one atomic unit: the DB column rename, model, Pydantic schemas, service/router/directory references, and the Alembic migration must land together or the `migrated_database` integration fixture desyncs from the models.

**Files:**
- Create: `backend/migrations/versions/2026_07_14_0082_unify_attestor_taxonomy.py`
- Modify: `backend/app/modules/organizations/models.py:322,416` (rename column attribute)
- Modify: `backend/app/modules/organizations/schemas.py` (field rename, validators, `max_length`)
- Modify: `backend/app/modules/organizations/attestor_application_service.py:196,323,645,853`
- Modify: `backend/app/modules/organizations/router.py:157`
- Modify: `backend/app/modules/attestation/directory_service.py:53,103` and params
- Modify: `backend/app/modules/attestation/schemas.py:478,516`
- Modify: `backend/app/modules/attestation/router.py:216,224`
- Delete: `backend/app/modules/attestation/taxonomy.py`
- Test: `backend/tests/integration/test_org_attestor_application_endpoints.py` (existing; extend), `backend/tests/unit/test_attestor_taxonomy_migration.py` (new)

**Interfaces:**
- Consumes: `validate_sectors`, `validate_functions`, `validate_jurisdictions` from `app.shared.taxonomy` (Task 1).
- Produces: attestor application/profile field `functions` (was `framework_categories`) on models, `OrgAttestorApplicationCreateRequest`/`UpdateRequest`/`Response`, and `AttestorDirectoryEntry`; directory filter kwarg `function` (was `framework_category`).

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/unit/test_attestor_taxonomy_migration.py`:

```python
"""Verifies the taxonomy-unification migration remaps legacy attestor vocab."""

from __future__ import annotations

from migrations.versions import (
    unify_attestor_taxonomy as mig,  # type: ignore[attr-defined]
)


def test_sector_map_is_canonical():
    """Legacy sector labels map to canonical framework slugs."""
    assert mig.SECTOR_MAP["PE"] == "private_equity"
    assert mig.SECTOR_MAP["Real Estate"] == "real_estate"


def test_function_map_covers_all_nine_legacy_categories():
    """All nine legacy categories map, including the two misfits."""
    assert mig.FUNCTION_MAP["Technology"] == "engineering"
    assert mig.FUNCTION_MAP["Investment Management"] == "investment_management"
    assert len(mig.FUNCTION_MAP) == 9


def test_remap_array_leaves_unknown_values_untouched():
    """Unmapped values pass through unchanged (never dropped)."""
    assert mig._remap_array(["PE", "UnknownSector"], mig.SECTOR_MAP) == [
        "private_equity",
        "UnknownSector",
    ]
```

The migration module import path uses the file stem; name the file so the stem is `2026_07_14_0082_unify_attestor_taxonomy` but expose `unify_attestor_taxonomy` via the `migrations/versions` package is not importable by that dotted name (leading digits). Instead import by loading is awkward — so put the pure helpers (`SECTOR_MAP`, `FUNCTION_MAP`, `JURISDICTION_MAP`, `_remap_array`) in the migration file AND re-export them from a plain module `backend/migrations/attestor_taxonomy_remap.py`, and have the test import from there:

Replace the test's import line with:

```python
from migrations import attestor_taxonomy_remap as mig
```

- [ ] **Step 2: Create the pure remap helpers**

Create `backend/migrations/attestor_taxonomy_remap.py`:

```python
"""Pure value-remap tables for the attestor taxonomy-unification migration.

Kept import-safe (no Alembic context) so the mappings can be unit-tested and
reused by the migration's upgrade/downgrade without duplication.
"""

from __future__ import annotations

SECTOR_MAP: dict[str, str] = {
    "PE": "private_equity",
    "VC": "venture_capital",
    "Infrastructure": "infrastructure",
    "Real Estate": "real_estate",
}

FUNCTION_MAP: dict[str, str] = {
    "Compliance": "compliance",
    "Governance": "governance",
    "Risk": "risk_management",
    "Operations": "operations",
    "Legal": "legal",
    "Finance": "finance",
    "HR": "human_resources",
    "Technology": "engineering",
    "Investment Management": "investment_management",
}

JURISDICTION_MAP: dict[str, str] = {
    "Global": "global",
    "European Union": "european_union",
    "Australia": "australia",
    "Brazil": "brazil",
    "Canada": "canada",
    "China": "china",
    "France": "france",
    "Germany": "germany",
    "Hong Kong": "hong_kong",
    "India": "india",
    "Ireland": "ireland",
    "Japan": "japan",
    "Kenya": "kenya",
    "Mexico": "mexico",
    "Netherlands": "netherlands",
    "New Zealand": "new_zealand",
    "Nigeria": "nigeria",
    "Saudi Arabia": "saudi_arabia",
    "Singapore": "singapore",
    "South Africa": "south_africa",
    "Switzerland": "switzerland",
    "United Arab Emirates": "united_arab_emirates",
    "United Kingdom": "united_kingdom",
    "United States": "united_states",
}


def _remap_array(values: list[str], mapping: dict[str, str]) -> list[str]:
    """Remap known values; pass unknown values through unchanged."""
    return [mapping.get(value, value) for value in values]
```

- [ ] **Step 3: Run the migration test to verify it fails, then passes**

Run: `cd backend && uv run pytest tests/unit/test_attestor_taxonomy_migration.py -v`
Expected first run: FAIL (module missing) → after Step 2 exists: PASS (3 tests).

- [ ] **Step 4: Write the Alembic migration**

Create `backend/migrations/versions/2026_07_14_0082_unify_attestor_taxonomy.py`:

```python
"""Unify attestor taxonomy with framework taxonomy.

Renames the attestor ``framework_categories`` column to ``functions`` on both
the application and profile tables (the name collided with the doc-type
``Framework.category``), and remaps existing attestor rows from the legacy
4-sector / 9-category vocabulary to the canonical framework slugs. Supports the
AMM field-fix so attestor expertise and framework tags share one vocabulary.

Unmapped jurisdiction free-text is left as-is and logged for manual cleanup —
no attestor data is dropped.

Revision ID: 2026_07_14_0082
Revises: 2026_07_13_0081
Create Date: 2026-07-14
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import text

from alembic import op
from migrations.attestor_taxonomy_remap import (
    FUNCTION_MAP,
    JURISDICTION_MAP,
    SECTOR_MAP,
    _remap_array,
)

revision = "2026_07_14_0082"
down_revision = "2026_07_13_0081"
branch_labels = None
depends_on = None

_TABLES = ("org_attestor_applications", "org_attestor_profiles")


def _remap_rows(new_function_col: bool) -> None:
    """Remap sector/function/jurisdiction arrays on both attestor tables.

    Args:
        new_function_col: When True the function column is named ``functions``
            (post-rename, used by upgrade); when False it is
            ``framework_categories`` (used by downgrade).
    """
    bind = op.get_bind()
    fn_col = "functions" if new_function_col else "framework_categories"
    sector_map = SECTOR_MAP if new_function_col else {v: k for k, v in SECTOR_MAP.items()}
    fn_map = FUNCTION_MAP if new_function_col else {v: k for k, v in FUNCTION_MAP.items()}
    juris_map = (
        JURISDICTION_MAP
        if new_function_col
        else {v: k for k, v in JURISDICTION_MAP.items()}
    )
    for table in _TABLES:
        rows = bind.execute(
            text(f"SELECT id, sectors, {fn_col}, jurisdictions FROM {table}")
        ).fetchall()
        for row in rows:
            new_sectors = _remap_array(list(row.sectors or []), sector_map)
            new_functions = _remap_array(list(getattr(row, fn_col) or []), fn_map)
            new_jurisdictions = _remap_array(list(row.jurisdictions or []), juris_map)
            unmapped = [
                value
                for value in (row.jurisdictions or [])
                if value not in juris_map and value not in JURISDICTION_MAP.values()
            ]
            if unmapped:
                logger.bind(
                    module="migration", action="unify_attestor_taxonomy", table=table
                ).warning(f"unmapped_jurisdictions row={row.id} values={unmapped}")
            bind.execute(
                text(
                    f"UPDATE {table} SET sectors = :s, {fn_col} = :f, "
                    "jurisdictions = :j WHERE id = :id"
                ),
                {
                    "s": new_sectors,
                    "f": new_functions,
                    "j": new_jurisdictions,
                    "id": row.id,
                },
            )


def upgrade() -> None:
    """Rename the column, then remap legacy values to canonical slugs."""
    for table in _TABLES:
        op.alter_column(table, "framework_categories", new_column_name="functions")
    _remap_rows(new_function_col=True)


def downgrade() -> None:
    """Reverse the value remap, then rename the column back."""
    _remap_rows(new_function_col=False)
    for table in _TABLES:
        op.alter_column(table, "functions", new_column_name="framework_categories")
```

- [ ] **Step 5: Rename the ORM columns**

In `backend/app/modules/organizations/models.py`, change both occurrences (lines ~322 and ~416) from:

```python
    framework_categories: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
```

to:

```python
    functions: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
```

- [ ] **Step 6: Update org Pydantic schemas**

In `backend/app/modules/organizations/schemas.py`:

Change the import on line 28 from:

```python
from app.modules.attestation.taxonomy import validate_categories, validate_sectors
```

to:

```python
from app.shared.taxonomy import (
    validate_functions,
    validate_jurisdictions,
    validate_sectors,
)
```

In `OrgAttestorApplicationCreateRequest`, replace the sector/category/jurisdiction fields and validators:

```python
    sectors: list[str] = Field(min_length=1, max_length=12)
    functions: list[str] = Field(min_length=1, max_length=14)
    jurisdictions: list[str] = Field(min_length=1, max_length=25)
```

```python
    @field_validator("sectors")
    @classmethod
    def _clean_sectors(cls, value: list[str]) -> list[str]:
        """Validate sectors against the canonical taxonomy."""
        return validate_sectors(value)

    @field_validator("functions")
    @classmethod
    def _clean_functions(cls, value: list[str]) -> list[str]:
        """Validate functions against the canonical taxonomy."""
        return validate_functions(value)

    @field_validator("jurisdictions")
    @classmethod
    def _clean_jurisdictions(cls, value: list[str]) -> list[str]:
        """Validate jurisdictions against the canonical taxonomy."""
        return validate_jurisdictions(value)
```

Apply the mirror changes in `OrgAttestorApplicationUpdateRequest` (optional variants):

```python
    sectors: list[str] | None = Field(default=None, min_length=1, max_length=12)
    functions: list[str] | None = Field(default=None, min_length=1, max_length=14)
    jurisdictions: list[str] | None = Field(default=None, min_length=1, max_length=25)
```

```python
    @field_validator("sectors")
    @classmethod
    def _clean_sectors(cls, value: list[str] | None) -> list[str] | None:
        """Validate sectors against the canonical taxonomy when supplied."""
        return validate_sectors(value) if value is not None else None

    @field_validator("functions")
    @classmethod
    def _clean_functions(cls, value: list[str] | None) -> list[str] | None:
        """Validate functions against the canonical taxonomy when supplied."""
        return validate_functions(value) if value is not None else None

    @field_validator("jurisdictions")
    @classmethod
    def _clean_jurisdictions(cls, value: list[str] | None) -> list[str] | None:
        """Validate jurisdictions against the canonical taxonomy when supplied."""
        return validate_jurisdictions(value) if value is not None else None
```

In `OrgAttestorApplicationResponse`, rename the field:

```python
    sectors: list[str]
    functions: list[str]
    jurisdictions: list[str]
```

- [ ] **Step 7: Update service, router, and directory references**

In `backend/app/modules/organizations/attestor_application_service.py`:
- Line ~196 (create): `framework_categories=payload.framework_categories,` → `functions=payload.functions,`
- Line ~323 (update apply — locate the `framework_categories` assignment in `update_org_attestor_application`) → `functions`
- Lines ~645 (`_org_profile_specializations`): change the loop to read the renamed field:

```python
def _org_profile_specializations(application: OrgAttestorApplication) -> list[str]:
    """Derive legacy-matcher specializations from onboarding taxonomy fields."""
    values: list[str] = []
    for item in [*application.sectors, *application.functions]:
        if item not in values:
            values.append(item)
    return values
```

- Line ~853 (profile create): `framework_categories=application.framework_categories,` → `functions=application.functions,`

In `backend/app/modules/organizations/router.py:157`: `framework_categories=application.framework_categories,` → `functions=application.functions,`

In `backend/app/modules/attestation/directory_service.py`:
- Rename the kwarg `framework_category: str | None` → `function: str | None` in `list_directory`.
- Line ~53: `OrgAttestorProfile.framework_categories.op("&&")([framework_category])` → `OrgAttestorProfile.functions.op("&&")([function])` guarded by `if function is not None:`
- Line ~103 (`_directory_entry`): `framework_categories=profile.framework_categories,` → `functions=profile.functions,`

In `backend/app/modules/attestation/schemas.py`:
- Line ~478 (`AttestorDirectoryEntry`): `framework_categories: list[str]` → `functions: list[str]`
- Line ~516 (directory filter schema): `framework_category: str` → `function: str`

In `backend/app/modules/attestation/router.py`:
- Line ~216: `framework_category: str | None = Query(default=None),` → `function: str | None = Query(default=None),`
- Line ~224: `framework_category=framework_category,` → `function=function,`

- [ ] **Step 8: Delete the old attestor taxonomy module**

```bash
cd backend && git rm app/modules/attestation/taxonomy.py
```

Then grep to confirm no references remain:

Run: `cd backend && grep -rn "attestation.taxonomy\|validate_categories\|framework_categories" app/`
Expected: no matches.

- [ ] **Step 9: Extend the application endpoint test (canonical values + rename)**

In `backend/tests/integration/test_org_attestor_application_endpoints.py` (find the existing create/submit test that posts `framework_categories`), update the payload to the canonical vocabulary and renamed field, and assert 422 on off-vocabulary. Replace the taxonomy portion of the create payload with:

```python
    payload = {
        # ... existing legal_name / credentials_summary / references ...
        "sectors": ["private_equity"],
        "functions": ["compliance", "investment_management"],
        "jurisdictions": ["united_states"],
    }
    res = await client.post(
        f"/v1/orgs/{org_id}/attestor-application", json=payload, headers=auth(owner_token)
    )
    assert res.status_code in (200, 201)
    assert res.json()["functions"] == ["compliance", "investment_management"]

    bad = {**payload, "functions": ["Compliance"]}  # legacy label, off-vocabulary
    res_bad = await client.post(
        f"/v1/orgs/{org_id}/attestor-application", json=bad, headers=auth(owner_token)
    )
    assert res_bad.status_code == 422
```

(Adjust the endpoint path/fixtures to match the file's existing helpers.)

- [ ] **Step 10: Run migration up/down and the suite**

```bash
cd backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run pytest tests/integration/test_org_attestor_application_endpoints.py tests/unit/test_attestor_taxonomy_migration.py -q
```
Expected: migrations succeed both directions; tests PASS.

- [ ] **Step 11: Lint + commit**

```bash
cd backend
uv run ruff check . && uv run mypy app
git add -A
git commit -m "Rename attestor framework_categories to functions and adopt canonical taxonomy"
```

---

### Task 3: Fix AMM matching to use framework fields

**Files:**
- Modify: `backend/app/modules/attestation/scoring.py`
- Modify: `backend/app/modules/attestation/matching_service.py`
- Test: `backend/tests/unit/test_scoring.py` (existing; extend), `backend/tests/integration/test_attestation_matching.py` (existing; extend — confirm actual filename with `ls backend/tests`)

**Interfaces:**
- Consumes: renamed profile field `functions` (Task 2); canonical `Framework.sector`/`function`/`jurisdiction`.
- Produces: `scoring.function_match(framework_function: str | None, profile_functions: list[str]) -> float`; `WEIGHTS` key `"function"` (was `"category"`); matching derives sector/function/jurisdiction from the framework for framework targets.

- [ ] **Step 1: Write the failing scoring test**

Add to `backend/tests/unit/test_scoring.py`:

```python
def test_function_match_hits_on_framework_function():
    """A framework function present in the profile scores 1.0."""
    from app.modules.attestation import scoring

    assert scoring.function_match("risk_management", ["compliance", "risk_management"]) == 1.0


def test_function_match_misses_when_absent():
    """A framework function absent from the profile scores 0.0."""
    from app.modules.attestation import scoring

    assert scoring.function_match("engineering", ["compliance"]) == 0.0


def test_function_match_neutral_when_no_function():
    """Non-framework targets (no function) score the neutral 1.0."""
    from app.modules.attestation import scoring

    assert scoring.function_match(None, ["compliance"]) == 1.0


def test_weights_use_function_key_and_sum_to_one():
    """The weight key is 'function' (not 'category') and weights still sum to 1."""
    from app.modules.attestation import scoring

    assert "function" in scoring.WEIGHTS
    assert "category" not in scoring.WEIGHTS
    assert round(sum(scoring.WEIGHTS.values()), 5) == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_scoring.py -k "function_match or weights_use_function" -v`
Expected: FAIL — `scoring.function_match` not defined; `"function"` not in WEIGHTS.

- [ ] **Step 3: Rename in `scoring.py`**

Change `WEIGHTS` (line 12):

```python
WEIGHTS: Final[dict[str, float]] = {
    "sector": 0.30,
    "function": 0.25,
    "credential": 0.20,
    "availability": 0.15,
    "reputation": 0.10,
}
```

Rename `category_match` → `function_match`:

```python
def function_match(
    framework_function: str | None,
    profile_functions: list[str],
) -> float:
    """Score whether a framework request's function matches the profile.

    Args:
        framework_function: The framework's ``function`` for framework targets,
            or ``None`` for non-framework targets.
        profile_functions: Functions listed on the Attestor profile.

    Returns:
        ``1.0`` when the function matches or no function applies, ``0.0``
        otherwise.
    """
    if framework_function is None:
        return 1.0
    functions = {value.casefold() for value in profile_functions}
    return 1.0 if framework_function.casefold() in functions else 0.0
```

- [ ] **Step 4: Run scoring tests**

Run: `cd backend && uv run pytest tests/unit/test_scoring.py -v`
Expected: PASS (update any existing `category_match`/`"category"` assertions in this file to the new names as part of this step).

- [ ] **Step 5: Write the failing matching integration test**

Add to the attestation matching integration test file a framework-target case proving sector+function align from the framework and jurisdiction gates on it. Use the file's existing factories/fixtures; the assertion shape:

```python
async def test_framework_target_matches_on_framework_fields(...):
    """A framework whose sector/function/jurisdiction match the attestor profile
    yields a scored candidate; a jurisdiction-disjoint attestor is filtered out.
    """
    # Framework tagged sector=private_equity, function=risk_management, jurisdiction=united_states
    # Attestor A profile: sectors=[private_equity], functions=[risk_management],
    #                      jurisdictions=[united_states]  -> candidate present, sector & function factors = 1.0
    # Attestor B profile: same sectors/functions but jurisdictions=[nigeria] -> filtered out
    candidates = await matching_service._rank_eligible_attestors(
        db, attestation=attestation, excluded_ids=set(), limit=10, now=now
    )
    org_ids = {c.org_id for c in candidates}
    assert attestor_a_org_id in org_ids
    assert attestor_b_org_id not in org_ids
    a = next(c for c in candidates if c.org_id == attestor_a_org_id)
    assert a.breakdown["sector"] == 1.0
    assert a.breakdown["function"] == 1.0
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestation_matching.py -k framework_target -v`
Expected: FAIL — candidate B not filtered / breakdown uses old `category` key / sector derived from `requested_specializations`.

- [ ] **Step 7: Add framework-context helpers in `matching_service.py`**

Replace `_framework_category` (lines ~981-990) with three helpers:

```python
async def _framework_axes(
    db: AsyncSession, attestation: Attestation
) -> tuple[str | None, str | None, str | None]:
    """Return (sector, function, jurisdiction) for a framework target, else Nones.

    For non-framework targets every axis is ``None`` so matching falls back to
    the requester-supplied specialization/jurisdiction lists.
    """
    if attestation.target_type != "framework":
        return None, None, None
    row = (
        await db.execute(
            select(
                Framework.sector, Framework.business_function, Framework.jurisdiction
            ).where(Framework.id == attestation.target_id)
        )
    ).one_or_none()
    if row is None:
        return None, None, None
    return row.sector, row.business_function, row.jurisdiction
```

(Note: the ORM attribute is `business_function`, mapped to the `function` column — see `frameworks/models.py:167`.)

- [ ] **Step 8: Rewire eligibility filters and factors in `_rank_eligible_attestors`**

Replace the hard-filter `.where(...)` block (matching_service.py ~1054-1067) so framework targets gate on framework-derived sector + jurisdiction, and non-framework targets keep the requester lists. Build the query in stages:

```python
    is_framework = attestation.target_type == "framework"
    fw_sector, fw_function, fw_jurisdiction = await _framework_axes(db, attestation)

    query = (
        select(OrgAttestorProfile)
        .join(Organization, Organization.id == OrgAttestorProfile.org_id)
        .join(
            OrgCapability,
            (OrgCapability.org_id == OrgAttestorProfile.org_id)
            & (OrgCapability.capability == "attestor")
            & (OrgCapability.status == "active"),
        )
        .where(
            OrgAttestorProfile.active.is_(True),
            Organization.suspended_at.is_(None),
            Organization.deactivated_at.is_(None),
            OrgAttestorProfile.coi_signed_at.is_not(None),
            OrgAttestorProfile.coi_expires_at > now,
        )
    )

    if is_framework:
        # Sector gate: only when the framework declares a sector.
        if fw_sector is not None:
            query = query.where(OrgAttestorProfile.sectors.op("&&")([fw_sector]))
        # Jurisdiction gate: skip when the framework is global or unscoped;
        # otherwise the attestor must cover that jurisdiction or be global.
        if fw_jurisdiction is not None and fw_jurisdiction != "global":
            query = query.where(
                OrgAttestorProfile.jurisdictions.op("&&")(
                    [fw_jurisdiction, "global"]
                )
            )
    else:
        query = query.where(
            OrgAttestorProfile.specializations.op("&&")(
                sql_cast(attestation.requested_specializations, ARRAY(Text))
            ),
            OrgAttestorProfile.jurisdictions.op("&&")(
                sql_cast(attestation.requested_jurisdictions, ARRAY(Text))
            ),
        )
```

Replace the removed `framework_category = await _framework_category(db, attestation)` line (~1093) — `fw_*` are already computed above.

Change the `factors` dict (~1118-1133) to derive sector from the framework and use the function match:

```python
        factors = {
            "sector": scoring.sector_alignment(
                [fw_sector] if fw_sector is not None else attestation.requested_specializations,
                profile.sectors,
                profile.specializations,
            ),
            "function": scoring.function_match(fw_function, profile.functions),
            "credential": scoring.credential_relevance(),
            "availability": scoring.availability_score(
                min(active_count, concurrency_cap), concurrency_cap
            ),
            "reputation": scoring.reputation_score(rep_norm),
        }
```

- [ ] **Step 9: Run matching + scoring tests**

Run: `cd backend && uv run pytest tests/unit/test_scoring.py tests/integration/test_attestation_matching.py -q`
Expected: PASS.

- [ ] **Step 10: Lint + commit**

```bash
cd backend
uv run ruff check . && uv run mypy app
git add app/modules/attestation/scoring.py app/modules/attestation/matching_service.py tests/
git commit -m "Repoint AMM matching at framework sector/function/jurisdiction"
```

---

### Task 4: Relax attestation-request schema for framework targets

Framework targets no longer need requester-typed specializations/jurisdictions (matching derives them). Make those optional for framework targets, required otherwise.

**Files:**
- Modify: `backend/app/modules/attestation/schemas.py` (`AttestationRequestCreateRequest`)
- Test: `backend/tests/integration/test_attestation_endpoints.py` (existing; extend)

**Interfaces:**
- Produces: `requested_specializations`/`requested_jurisdictions` default to `[]` and are only required (≥1) when `target_type != "framework"`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_attestation_endpoints.py`:

```python
async def test_framework_attestation_request_needs_no_specializations(...):
    """A framework-target request succeeds without requested_specializations."""
    body = {
        "target_type": "framework",
        "target_id": str(framework_id),
        "review_type": "standard",
        # no requested_specializations / requested_jurisdictions
    }
    res = await client.post("/v1/attestations", json=body, headers=auth(token))
    assert res.status_code in (200, 201)


async def test_non_framework_request_still_requires_specializations(...):
    """A contributor-target request without specializations is rejected 422."""
    body = {
        "target_type": "contributor",
        "target_id": str(user_id),
        "review_type": "standard",
    }
    res = await client.post("/v1/attestations", json=body, headers=auth(token))
    assert res.status_code == 422
```

(Match the actual request endpoint path and required fields — check the file's existing request tests.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_attestation_endpoints.py -k "framework_attestation_request_needs_no or non_framework_request_still" -v`
Expected: FAIL — framework request 422s on missing `requested_specializations`.

- [ ] **Step 3: Relax the schema**

In `backend/app/modules/attestation/schemas.py`, `AttestationRequestCreateRequest` (~line 326), change the two list fields to default-empty and add a model validator:

```python
    requested_specializations: list[str] = Field(default_factory=list, max_length=25)
    requested_jurisdictions: list[str] = Field(default_factory=list, max_length=25)
```

Add (import `model_validator` from pydantic if not already imported):

```python
    @model_validator(mode="after")
    def _require_lists_for_non_framework(self) -> "AttestationRequestCreateRequest":
        """Non-framework targets must name at least one specialization + jurisdiction.

        Framework targets derive both from the framework's own tags, so the
        requester may omit them.
        """
        if self.target_type != "framework":
            if not self.requested_specializations:
                raise ValueError("requested_specializations is required.")
            if not self.requested_jurisdictions:
                raise ValueError("requested_jurisdictions is required.")
        return self
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_attestation_endpoints.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd backend
uv run ruff check . && uv run mypy app
git add app/modules/attestation/schemas.py tests/integration/test_attestation_endpoints.py
git commit -m "Make attestation request specializations optional for framework targets"
```

---

### Task 5: Regenerate OpenAPI + frontend client, add investment_management option

**Files:**
- Modify: `contracts/openapi.yaml` (regenerated)
- Modify: `frontend/src/lib/generated/{sdk.gen.ts,types.gen.ts}` (regenerated)
- Modify: `frontend/src/lib/marketplace/taxonomy.ts`

**Interfaces:**
- Produces: generated types with attestor `functions` (was `framework_categories`), directory `function` query param, `investment_management` in the `FrameworkFunction` union; `FUNCTION_OPTIONS` includes Investment Management.

- [ ] **Step 1: Regenerate the OpenAPI contract**

```bash
cd backend
uv run python -c "import yaml; from app.main import app; \
f=open('../contracts/openapi.yaml','w'); \
yaml.safe_dump(app.openapi(), f, sort_keys=False, allow_unicode=True); f.close()"
```

Verify the rename landed:

Run: `grep -c "framework_categories" contracts/openapi.yaml`
Expected: `0`.

- [ ] **Step 2: Regenerate the frontend client**

```bash
cd frontend && npm run generate:api
```

Run: `grep -c "framework_categories" frontend/src/lib/generated/types.gen.ts`
Expected: `0`. And confirm `investment_management` appears in the generated `FrameworkFunction` union.

- [ ] **Step 3: Add the option in marketplace taxonomy**

In `frontend/src/lib/marketplace/taxonomy.ts`, append to `FUNCTION_OPTIONS` (before the closing `] as const`):

```typescript
  { label: "Investment Management", value: "investment_management" },
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: clean (the new option satisfies the regenerated `FrameworkFunction` type).

- [ ] **Step 5: Commit**

```bash
cd /Users/a0000/projects/auracles
git add contracts/openapi.yaml frontend/src/lib/generated/ frontend/src/lib/marketplace/taxonomy.ts
git commit -m "Regenerate API client for taxonomy rename; add Investment Management option"
```

---

### Task 6: Point attestor apply form at canonical taxonomy

**Files:**
- Modify: `frontend/src/components/modules/organizations/attestor/apply-gate.tsx`
- Modify: `frontend/src/components/modules/organizations/attestor/apply-gate.test.tsx`

**Interfaces:**
- Consumes: `SECTOR_OPTIONS`, `FUNCTION_OPTIONS`, `JURISDICTION_OPTIONS` from `@/lib/marketplace/taxonomy`; generated `functions` field.

- [ ] **Step 1: Update the test to canonical values + functions field**

In `apply-gate.test.tsx`, change the sector/function selections and assertions:

```typescript
    fireEvent.change(screen.getByLabelText(/Sectors/i), {
      target: { value: "private_equity" },
    });
    fireEvent.change(screen.getByLabelText(/Functions/i), {
      target: { value: "compliance" },
    });
    fireEvent.change(screen.getByLabelText(/Jurisdictions/i), {
      target: { value: "united_states" },
    });
    // ...
    const body = vi.mocked(createOrgAttestorApplication).mock.calls[0][0].body;
    expect(body.sectors).toEqual(["private_equity"]);
    expect(body.functions).toEqual(["compliance"]);
    expect(body.jurisdictions).toEqual(["united_states"]);
```

And in the friendly-label chip test, select `private_equity` and assert the chip renders `Private Equity`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/modules/organizations/attestor/apply-gate.test.tsx`
Expected: FAIL — form still uses attestor's 4-value `SECTOR_OPTIONS` and `framework_categories`.

- [ ] **Step 3: Swap the form to canonical options and the `functions` field**

In `apply-gate.tsx`:
- Remove the local `SECTOR_OPTIONS` and `CATEGORY_OPTIONS` constants.
- Import canonical lists:

```typescript
import {
  SECTOR_OPTIONS,
  FUNCTION_OPTIONS,
  JURISDICTION_OPTIONS,
} from "@/lib/marketplace/taxonomy";
```

- Rename the form-state key and body field `framework_categories` → `functions` (in `formData` init from `application?.functions`, in `handleSaveDraft`/`handleSubmit` bodies, and the `ListField` union).
- Change the second `MultiAddSelect` to:

```tsx
        <MultiAddSelect
          label="Functions"
          placeholder="Add a function"
          hint="Select at least one function you specialize in."
          options={FUNCTION_OPTIONS}
          selected={formData.functions}
          disabled={!canEdit}
          onAdd={(value) => addValue("functions", value)}
          onRemove={(value) => removeValue("functions", value)}
        />
```

- The `MultiAddSelect` `options` prop type is `readonly TaxonomyOption[]`; the marketplace options are `readonly MarketplaceOption[]` with the same `{ label, value }` shape — change `MultiAddSelect`'s `options` type to `readonly { label: string; value: string }[]` so both fit, or import `MarketplaceOption` and use it.

- [ ] **Step 4: Run tests + typecheck + lint**

```bash
cd frontend
npx vitest run src/components/modules/organizations/attestor/apply-gate.test.tsx
npx tsc --noEmit
npx eslint src/components/modules/organizations/attestor/apply-gate.tsx
```
Expected: tests PASS, tsc + eslint clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/a0000/projects/auracles
git add frontend/src/components/modules/organizations/attestor/apply-gate.tsx frontend/src/components/modules/organizations/attestor/apply-gate.test.tsx
git commit -m "Point attestor apply form at canonical sector/function/jurisdiction taxonomy"
```

---

### Task 7: Hide specializations input for framework attestation requests

**Files:**
- Modify: `frontend/src/components/modules/attestation/requestor-panel.tsx`
- Test: `frontend/src/components/modules/attestation/requestor-panel.test.tsx` (create if absent)

**Interfaces:**
- Consumes: `target_type` state already present (`requestor-panel.tsx:37`).

- [ ] **Step 1: Write the failing test**

Create/extend `requestor-panel.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RequestorPanel } from "./requestor-panel";

describe("RequestorPanel specializations visibility", () => {
  it("hides the specializations input for framework targets", () => {
    render(<RequestorPanel /* required props/mocks */ />);
    // Default target type is "framework".
    expect(screen.queryByLabelText(/specializations/i)).toBeNull();
  });
});
```

(Wire whatever props/mocks the panel needs; follow the financials-tab test for the mocking pattern.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/modules/attestation/requestor-panel.test.tsx`
Expected: FAIL — specializations input rendered for framework targets.

- [ ] **Step 3: Gate the input on target type**

In `requestor-panel.tsx`:
- Wrap the specializations field (the block around line 185 using `value={specializations}`) in `{targetType !== "framework" && ( ... )}`.
- In the submit handler (line ~75-76), only send the lists for non-framework targets:

```typescript
        requested_jurisdictions: targetType === "framework" ? [] : splitCsv(jurisdictions),
        requested_specializations: targetType === "framework" ? [] : splitCsv(specializations),
```

- Update the `canSubmit`/validity check (line ~40) so `isNonEmpty(specializations)` is only required when `targetType !== "framework"`.

- [ ] **Step 4: Run tests + typecheck + lint**

```bash
cd frontend
npx vitest run src/components/modules/attestation/requestor-panel.test.tsx
npx tsc --noEmit
npx eslint src/components/modules/attestation/requestor-panel.tsx
```
Expected: tests PASS, clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/a0000/projects/auracles
git add frontend/src/components/modules/attestation/requestor-panel.tsx frontend/src/components/modules/attestation/requestor-panel.test.tsx
git commit -m "Hide specialization input for framework attestation requests"
```

---

## Final verification

- [ ] Backend suite green: `cd backend && uv run pytest -q`
- [ ] Backend lint/type clean: `uv run ruff check . && uv run mypy app`
- [ ] Migrations reversible: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- [ ] Frontend: `cd frontend && npx vitest run && npx tsc --noEmit && npx eslint src`
- [ ] Manual: create an attestor application with canonical sector/function/jurisdiction → submits; request a framework attestation without typing specializations → succeeds; confirm an attestor whose function/sector/jurisdiction match a framework is now returned by matching.
- [ ] No `framework_categories` remains anywhere: `grep -rn "framework_categories" backend/app frontend/src contracts` → no matches.

## Self-review notes

- Spec coverage: canonical module (T1), rename + validators + migration (T2), matching field-fix incl. hard-filter (T3), request relax (T4), client regen + option (T5), apply form (T6), request form (T7). All spec sections mapped.
- The spec under-specified the DB hard pre-filter; T3 Step 8 makes the framework-target eligibility gate explicit (sector overlap + jurisdiction overlap-with-global), consistent with locked decisions Q2/Q5.
- `Framework.function` is the ORM attribute `business_function` (column `function`) — T3 Step 7 notes this to avoid a wrong-attribute bug.
