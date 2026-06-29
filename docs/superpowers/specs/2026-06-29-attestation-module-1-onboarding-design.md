# Attestation Spec A — Module 1: Attestor Onboarding

- **Date:** 2026-06-29
- **Status:** Draft (awaiting review)
- **Author:** William Ikeji (architect) + agent
- **Module:** `attestation` (onboarding) + `settings` (KYC), `financials` (payout) touchpoints
- **Related FRs:** FR-ATT-*, BR-ATT-*
- **Source of truth:** `docs/Auracles Attestation — Product Development Workflow.md` §Module 1
- **Parent:** `2026-06-29-attestation-research-gap-analysis-design.md` (master gap analysis, Spec A)

## Purpose

Build the Attestor onboarding flow defined in Module 1 of the build guide: a one-time, gated
progression from application to an ACTIVE, directory-listed Attestor, advancing through
verification levels 1–4. This must be complete before the platform opens Attestor matching
(it is build priority 1).

This spec covers Module 1 only. Trial calibration is **stubbed** here (manual admin pass/fail);
its rubric-scored form arrives with Module 4 (Workspace, Spec D). Level 5 "Auracles Certified"
is computed from completed-attestation ratings and belongs to Module 6 (Spec E).

## Locked decisions (from brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Trial dependency on Module 4 rubric | **Stub trial** — record trial state + admin manual pass/fail on a seeded framework. Rubric-scored trial wired in at Module 4. |
| 2 | Flow model + level ladder | **Gated state machine, levels 1–4.** L5 "Certified" deferred to Spec E (needs ratings). |
| 3 | Credential cross-check (1.3) | **Manual + structured record.** Admin verifies against registry, records body + reference + good-standing. No registry API integration. |
| 4 | Taxonomy (1.5) | **Replace free-text `specializations[]`** with controlled `sectors[]` + `framework_categories[]`. Migrate existing data (admin re-tag). `jurisdictions[]` unchanged. |

## Current state being replaced

Today (`application_service.py`): application → admin `review_application` (admin 2FA) → on
approve, `_approve_attestor_profile_and_role` creates the `attestor` `UserRole` **and** an
`AttestorProfile` with `active=True` immediately. There is no KYC gate, credential cross-check,
CoI, trial, verification level, payout requirement, or directory.

This spec changes the approve path: the profile is created **only at ACTIVE**, after every gate
passes. `active=true` no longer flips at application approval.

## Onboarding state machine

`AttestorApplication.status` enum is extended; the application object drives the whole flow.

```
                 submit
        ──────────────────────────►  submitted
   (admin verifies KYC, name match)
        ──────────────────────────►  identity_verified        level 1
   (admin credential cross-check pass)
        ──────────────────────────►  professional_verified    level 2–3
   (admin assigns + decides trial = pass)
        ──────────────────────────►  expert_verified          level 3–4
   (CoI signed + taxonomy set + payout & tax complete)
        ──────────────────────────►  active                   profile published → directory

   rejected     — terminal (admin, with feedback)
   withdrawn    — terminal (owner, before active)
   held         — terminal-ish (2nd trial fail; admin re-opens)
```

- The four "prerequisites" for `active` (CoI, taxonomy, payout, tax doc) may be completed by the
  Attestor in any order during the flow, but `active` is **only** reachable once all are present
  **and** the trial has passed. Transition order between gates is enforced server-side;
  attempting to skip a gate returns `422`.
- `AttestorProfile` is created at the `active` transition (not earlier), copying the verified
  application data. `active=true` and `verification_level` are set then.
- The `attestor` `UserRole` is granted at `active` (an applicant is not yet a working Attestor).

### Verification levels

`verification_level` (int, 1–4) on `AttestorProfile`, set at the matching transition:

| Level | Reached at | Meaning |
|-------|-----------|---------|
| 1 | identity_verified | Identity verified (KYC) |
| 2–3 | professional_verified | Credential cross-checked, good standing |
| 3–4 | expert_verified / active | Trial passed |
| 5 | **deferred to Spec E** | Auracles Certified (10+ attestations, ≥4.5 avg) |

(Levels are coarse per the guide; exact 2-vs-3 / 3-vs-4 boundary derives from credential tier +
trial outcome — refined in Spec A implementation; never exceeds 4 here.)

## Data model changes

All additive Alembic migrations, backwards-compatible, `upgrade`/`downgrade` both tested. Enum
value additions use `ALTER TYPE ... ADD VALUE` (non-destructive).

### `attestor_applications`

- Extend status enum: add `submitted`, `identity_verified`, `professional_verified`,
  `expert_verified`, `active`, `held` (existing `pending`/`approved` retired via migration —
  map any existing `pending`→`submitted`, `approved`→`active`).
- Add: `linkedin_url` (Text, nullable), `professional_body_numbers` (JSONB — body→number),
  `cv_file_key` (Text, nullable — uploaded via the existing attestation upload-session pattern).
- **Legal name** (1.1): the applicant's full legal name comes from the existing `User` account
  (the registered identity), not a new application field. The 1.2 name-match compares the KYC
  provider's verified name against that `User` name; the boolean result is `kyc_name_match`. If
  the `User` model has no distinct legal-name field, add `legal_name` to the application as the
  authoritative value the match runs against — confirm against `auth.User` during implementation.
- CoI: `coi_declarations` (JSONB — list of `{entity, entity_type: firm|fund|individual,
  relationship: financial|advisory|employment, within_24mo: bool}`), `coi_signed_at`,
  `coi_expires_at` (signed_at + 1 year).
- Taxonomy: **replace** `specializations` (ARRAY Text) with `sectors` (ARRAY Text, controlled)
  and `framework_categories` (ARRAY Text, controlled). Keep `jurisdictions`. **Over-tagging
  penalty** (guide 1.5: "persistent over-tagging penalises AMM score") is an AMM-scoring rule —
  **deferred to Spec B (Module 3)** where the score is computed; Spec A only captures the tags.
- Identity/credential gate timestamps: `kyc_verified_at`, `kyc_name_match` (bool).

### `attestor_profiles`

- Add `verification_level` (Integer, not null, default 1), `sectors` (ARRAY Text),
  `framework_categories` (ARRAY Text); copy `coi_declarations`, `coi_signed_at`,
  `coi_expires_at`. Keep `jurisdictions`, `active`, `approved_at`.
- Replace the `specializations` GIN index with GIN indexes on `sectors` and
  `framework_categories` (matching inputs for Module 3 AMM).

### `credentials`

- Add `issuing_body` (ENUM: `cfa_institute|aicpa|isaca|rics|sra|state_bar|fca|acams|other`),
  `good_standing` (Boolean, nullable), `registry_checked_at`, `registry_checked_by`
  (FK users), `registry_reference` (Text). Reuses the existing manual `verification_status`
  flow in `credential_service.py`; cross-check populates these fields and gates L2–3.

### `attestor_trials` (new)

- `id`, `application_id` (FK), `seeded_framework_id` (FK frameworks, nullable),
  `status` (ENUM `assigned|passed|failed`), `attempt` (Integer, 1–2),
  `decided_by` (FK users, nullable), `decided_at`, `feedback` (Text, nullable),
  `created_at`. **Stub:** admin sets pass/fail manually; no rubric yet. 2nd `failed` →
  application `held`.

### Payout + tax

- Reuse `financials.PayoutAccount` for the payout method (bank/wire/stablecoin).
- Tax document: capture `tax_document_type` (`w9|w8ben|other`) + file key via the existing
  private upload-session + scan pattern (no new storage path). Required before `active`.

## API surface (additive, OpenAPI contract first)

**Applicant (auth'd, owner-scoped):**
- `POST /v1/attestor/application` — submit (extended fields incl. taxonomy).
- `PATCH /v1/attestor/application/{id}` — edit while pre-active.
- `POST /v1/attestor/application/{id}/coi` — submit + sign CoI declaration.
- `POST /v1/attestor/application/{id}/payout` — attach payout method (reuses financials).
- `POST /v1/attestor/application/{id}/tax-document` — upload tax doc (upload-session).
- `GET  /v1/attestor/application` — own application history + current state/level.

**Admin (auth'd, admin role, 2FA-gated — mirrors `review_application`):**
- `POST /v1/admin/attestor/applications/{id}/verify-kyc` — confirm KYC + name match → L1.
- `POST /v1/admin/attestor/applications/{id}/verify-credential` — record cross-check → L2–3.
- `POST /v1/admin/attestor/applications/{id}/trial` — assign seeded trial.
- `POST /v1/admin/attestor/applications/{id}/trial/{trial_id}/decide` — pass/fail trial.
- `POST /v1/admin/attestor/applications/{id}/reject` — reject with feedback.

**Public directory:**
- `GET /v1/attestors` — active attestors only; filter by sector / framework_category /
  jurisdiction / verification_level; returns name, credentials (verified only), tags, level
  badge, reputation (blank until Spec E), completed-attestation count (from `Attestation`).
- `GET /v1/attestors/{id}` — public attestor profile.

The existing single `review_application` endpoint is retired; its approve logic is replaced by
the gated transitions. OpenAPI updated first, then the frontend client regenerated.

## Service layer

Extend `application_service.py` (and a small `directory` read path):
- One transition function per gate, each: row-lock application → validate current state →
  advance status / set level → audit. Invalid current state → `422` (deny-by-default).
- `_create_active_profile` (replaces `_approve_attestor_profile_and_role`): runs only on the
  `active` transition, asserts all prerequisites present, creates profile + grants role.
- Trial: assign → `attestor_trials` row `assigned`; decide → `passed` advances level, `failed`
  increments attempt or `held` on 2nd fail.

## Security

- **Gate integrity** — `active` unreachable without every prior gate; each transition validated
  server-side, deny-by-default, `422` on skip. RBAC at the dependency layer (admin gates require
  admin role + verified TOTP, per existing `verify_totp_for_sensitive_action`).
- **PII** — CoI entities, tax documents, payout details, raw KYC docs **never** appear in the
  directory or any list endpoint. Directory exposes only verified credentials + coarse level.
- **Files** — CV + tax docs are private S3 via upload-session + virus scan; presigned access
  only, owner/admin scoped.
- **Audit** — every state transition and admin gate action written to the audit log
  (`module="attestation"`, actions `attestor_kyc_verified`, `attestor_credential_checked`,
  `attestor_trial_assigned`, `attestor_trial_passed/failed`, `attestor_coi_signed`,
  `attestor_activated`, `attestor_application_rejected`).
- **No secrets/PII in logs** — log `application_id` + state only, never CoI/tax/credential
  reference contents.

## Testing (TDD — vertical slices)

**Unit (service):**
- Each transition: valid advance succeeds; invalid current state → `422`.
- `active` requires KYC + credential + trial-pass + CoI + taxonomy + payout + tax — missing any
  → `422`; profile + role created only on success.
- Trial: pass → expert_verified; 1st fail → retry allowed; 2nd fail → `held`.
- Credential cross-check sets good-standing + gates level.
- Taxonomy migration: legacy `specializations` mapped / flagged for re-tag.

**Integration (endpoints):**
- Full happy path: submit → verify-kyc → verify-credential → trial pass → coi/payout/tax →
  active → appears in directory.
- Auth: applicant can't call admin gates (`403`); admin gate without TOTP → `401/403`.
- Directory: non-active attestors excluded; PII (CoI/tax/payout) never returned; filters by
  sector/category/jurisdiction/level work.
- Withdraw before active; reject with feedback; held after 2nd trial fail.

**Migration:** `alembic upgrade head` + `downgrade -1` succeed; enum value adds are non-destructive.

## Open questions / deferred

- **Level 2-vs-3 / 3-vs-4 boundary** — exact mapping of credential tier + trial outcome to the
  coarse level number; resolve during implementation (never exceeds 4 here).
- **Seeded trial framework source** — where the zero-fee calibration framework comes from
  (seeded fixture vs volunteer). Trial is stubbed, so a placeholder `seeded_framework_id`
  suffices for Spec A; finalize with Module 4.
- **KYC provider** — reuse existing `kyc_status` flow as-is (provider integration out of scope
  for this spec).
- **CoI annual re-sign enforcement** — `coi_expires_at` is stored here; the re-sign reminder /
  enforcement job is a small scheduled task — confirm whether it lands in Spec A or Spec B (AMM,
  where screening consumes it).

## Risks

- **Behavior change at approval** — profile/role no longer created at admin approve but at
  `active`. Any code reading `AttestorProfile` must tolerate its later creation; the migration
  maps legacy `approved`→`active` so existing approved attestors stay live.
- **Taxonomy migration** — replacing free-text `specializations` risks unmappable legacy values;
  mitigation: migrate best-effort + flag for admin re-tag, don't drop data silently.
- **Org-redefine rework** — verification levels, credential cross-check, personal CoI, and the
  directory's credential display are individual-specific; isolated so they re-point at org
  entities if the redefine lands. Flagged, not designed around.
