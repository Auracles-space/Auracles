# Taxonomy Unification + AMM Field-Fix — Design

**Date:** 2026-07-14
**Status:** Approved (design)
**Area:** Attestation matching (AMM), Frameworks taxonomy, Organizations (attestor profile/application)
**Related:** `2026-07-03` attestation redefine (Organizations subsystem); does not reopen its locked decisions.

## Problem

Attestor specialisation and framework tagging use **two incompatible controlled
vocabularies** for the same conceptual axes, and the AMM (Attestor Match Model)
compares the wrong framework fields. Result: for framework-target attestations,
the sector and function sub-scores are structurally near-zero and the
jurisdiction eligibility gate wrongly filters attestors out. The matcher does
not work end-to-end for its primary target type.

### Concrete defects (verified in code)

1. **Vocabulary mismatch.**
   - Framework (`backend/app/modules/frameworks/taxonomy.py`): `sector` (12,
     snake_case e.g. `private_equity`), `function` (13, e.g. `risk_management`),
     `category` (10 doc-types e.g. `playbook`), `industry` (14), `jurisdiction`
     (slugs via `frontend/src/lib/marketplace/taxonomy.ts`).
   - Attestor (`backend/app/modules/attestation/taxonomy.py`): `SECTORS` (4:
     `PE`,`VC`,`Infrastructure`,`Real Estate`), `FRAMEWORK_CATEGORIES` (9:
     `Compliance`,`Governance`,`Risk`… — semantically *functions*, not
     doc-types), `jurisdictions` free text.

2. **Wrong field compared.** `scoring.category_match` (weight **0.25**) compares
   `Framework.category` (doc-type) against the attestor `framework_categories`
   (functions). Casefold-exact → never intersects → sub-score always 0 for
   framework targets. The attestor field should match `Framework.function`.

3. **Sector disconnected from the framework.** `scoring.sector_alignment`
   (weight **0.30**) compares `Attestation.requested_specializations` (a
   free-text list the requester types) against the profile — never the
   framework's own `Framework.sector`. `private_equity` vs `PE` also fails
   casefold.

4. **Jurisdiction hard gate broken.** `matching_service` (~line 1061) filters
   candidates by array overlap of `Attestation.requested_jurisdictions` against
   `OrgAttestorProfile.jurisdictions` — both free text. `United States` vs `USA`
   → no overlap → attestor silently excluded.

## Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Canonical vocabulary | **Framework taxonomy is canonical.** Attestor adopts framework `sector`/`function`; the separate attestor taxonomy is deleted. |
| 2 | Source of "requested" values | For **framework targets**, matching derives sector/function/jurisdiction from the framework's own `Framework.sector`/`function`/`jurisdiction`. `requested_specializations` survives only for non-framework targets. |
| 3 | Attestor field rename | `framework_categories` → `functions` across DB, models, schemas, router, client, form. `specializations` retained as free-text expertise for **non-framework** matching only. |
| 4 | Misfit category mapping | `Technology`→`engineering`; **add** `investment_management` as a new canonical `function` (framework + attestor). No data lost. |
| 5 | Jurisdiction | Folded into this spec. Attestor `jurisdictions` become canonical `JURISDICTION_OPTIONS` slugs; framework targets derive the gate from `Framework.jurisdiction`. |

## Architecture

### Canonical taxonomy — single source

- New **`backend/app/shared/taxonomy.py`** holds the canonical controlled sets:
  `SECTORS` (12), `FUNCTIONS` (14 = existing 13 + `investment_management`),
  `CATEGORIES` (10 doc-types), `INDUSTRIES` (14), `JURISDICTIONS` (slugs), plus
  membership validators (`validate_sector`, `validate_function`,
  `validate_jurisdiction`, list variants).
- `frameworks/taxonomy.py` re-exports the `Literal` types from the shared module
  (framework write APIs unchanged in behavior).
- **Delete** `attestation/taxonomy.py`. Its `validate_sectors`/`validate_categories`
  consumers (`organizations/schemas.py`) switch to the shared validators.
- Frontend `lib/marketplace/taxonomy.ts`: add `investment_management` to
  `FUNCTION_OPTIONS`. Attestor form imports the shared framework option lists —
  no attestor-specific option arrays.

### Attestor data model (`organizations`)

- Rename column/field **`framework_categories` → `functions`** in
  `OrgAttestorProfile`, `OrgAttestorApplication` (and the pending-application
  table if separate), org `schemas.py` (`OrgAttestorApplicationCreate/Update/
  Response`), `router.py`, generated client, and `apply-gate.tsx`.
- `sectors` accepts canonical 12; `functions` accepts canonical 14;
  `jurisdictions` accepts canonical `JURISDICTION` slugs. All backend-validated.
- `specializations`: kept. Auto-derivation `= sectors + functions` (casefolded)
  retained so non-framework (person/credential) matching keeps signal.
  `_org_profile_specializations` updated to read the renamed field.

### Matching / AMM (`matching_service.py`, `scoring.py`)

- **Function match** (rename `category_match` → `function_match`): compare
  `Framework.function` vs `profile.functions`, casefold exact. New helper
  `_framework_function(db, attestation)` mirroring existing `_framework_category`.
  Rename `WEIGHTS` key `"category"` → `"function"` (0.25 unchanged). Non-framework
  target → `Framework.function` N/A → returns 1.0 (neutral), unchanged behavior.
- **Sector**: framework targets source the requested sector from
  `Framework.sector` via new helper `_framework_sector(db, attestation)`.
  Non-framework targets keep `requested_specializations` vs
  `profile.sectors + profile.specializations`.
- **Jurisdiction hard gate**: framework targets overlap `profile.jurisdictions`
  against `[Framework.jurisdiction]`. Edges: `Framework.jurisdiction` null →
  gate skipped (match all); `global` on either side → matches any. Non-framework
  → keep `requested_jurisdictions` overlap.
- Weight sum stays 1.0; scoring formula untouched — only inputs and
  field-pointers corrected.

### Migration (one Alembic revision, backwards-compatible)

- Rename column `org_attestor_profiles.framework_categories` → `functions`
  (+ application table + pending table). Rename preserves data.
- Remap `sectors`: `PE`→`private_equity`, `VC`→`venture_capital`,
  `Infrastructure`→`infrastructure`, `Real Estate`→`real_estate`.
- Remap `functions`: `Compliance`→`compliance`, `Governance`→`governance`,
  `Risk`→`risk_management`, `Operations`→`operations`, `Legal`→`legal`,
  `Finance`→`finance`, `HR`→`human_resources`, `Technology`→`engineering`,
  `Investment Management`→`investment_management`.
- Remap `jurisdictions`: best-effort free-text → slug (`United States`→
  `united_states`, `United Kingdom`→`united_kingdom`, `Nigeria`→`nigeria`, …).
  Unmapped values are **left as-is and logged**; migration docstring flags them
  for manual cleanup (do not drop data).
- Frameworks: **no migration** (already canonical).
- Historical `Attestation` rows: **not** migrated. Completed matches are
  immutable; new requests derive from the framework.
- `downgrade` reverses the column rename. Value remaps are documented as
  lossy-safe (reverse mapping applied where 1:1; `investment_management` and any
  merged values noted).

### Frontend

- **Apply form** (`apply-gate.tsx`): swap to canonical `SECTOR_OPTIONS` (12) and
  `FUNCTION_OPTIONS` (14) from the shared marketplace taxonomy; field
  `framework_categories` → `functions`. Existing `MultiAddSelect` dropdown-adds-
  to-list UX and canonical jurisdiction picker stay.
- **Attestation request form** (framework target): remove the free-text
  `requested_specializations` input — matching now derives from the framework.
  Keep it as a controlled picker only for non-framework targets.
- Update `contracts/openapi.yaml` (field rename, `investment_management`),
  regenerate the hey-api client.

## Testing (TDD, RED→GREEN per behavior)

Unit — `scoring`:
- `function_match` returns 1.0 when `Framework.function` ∈ `profile.functions`,
  0.0 otherwise; 1.0 (neutral) when function is None.
- `sector_alignment` scores from `Framework.sector` for framework targets.
- Jurisdiction gate: overlap hit; null framework jurisdiction → match all;
  `global` → match any; disjoint → filtered.

Unit — `matching_service`:
- Framework target whose sector/function/jurisdiction align → candidate scored
  > 0 and passes the gate.
- Mismatched jurisdiction → candidate excluded.

Migration:
- `upgrade` remaps a seeded old-vocab row (incl `Technology`→`engineering`,
  `Investment Management`→`investment_management`, a jurisdiction slug) correctly.
- `downgrade` reverses the column rename.
- `alembic upgrade head` + `downgrade -1` both succeed.

Integration — endpoints:
- Create/submit attestor application with canonical `sectors`/`functions`/
  `jurisdictions` → 2xx.
- Off-vocabulary value → 422.
- `investment_management` accepted by both framework write and attestor write.

Coverage gates unchanged (backend ≥ 80% on touched modules).

## Build slices (one at a time, backend before frontend, OpenAPI-first)

1. Shared taxonomy module (+ `investment_management`); `frameworks/taxonomy.py`
   re-export; framework write still green.
2. Attestor schema/model rename `framework_categories`→`functions` + canonical
   validators; OpenAPI + client regen; apply-form field/options swap.
3. Matching fix: `function_match` on `Framework.function`, sector from
   `Framework.sector`, jurisdiction gate from `Framework.jurisdiction`; weight
   key rename.
4. Alembic migration (column rename + data remap + jurisdiction best-effort).
5. Attestation request form: drop free-text specializations for framework
   targets.

## Risks

- **Data-integrity migration** on live attestor rows — value remaps reviewed by
  human before apply; unmapped jurisdictions logged, never dropped.
- **Cross-module coupling** — `attestation` and `organizations` import the shared
  taxonomy; acceptable (both already depend on `frameworks` models).
- **Behavior change in a matched, money-adjacent subsystem** — AMM ranking
  changes once fields are corrected. Historical attestations untouched; new
  matching validated by tests before merge.
- **Adding `investment_management`** widens the framework function enum — framework
  form gains one option; low blast radius.
