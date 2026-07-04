# Organizations as Attestors (Sub-project 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `attestor` org capability real end-to-end — org application → 8-gate vetting → activation → offers staffed by member reviewers → org settlement/payout/invoicing → org public identity — and retire the individual-attestor pipeline.

**Architecture:** New org-attestor tables live in `app/modules/organizations/`; the attestation module is re-pointed from `attestations.attestor_id` (users) to `attestor_org_id` (organizations) + `reviewing_member_id` (org_members, internal-only). Additive migrations first, code re-point in the middle, one final architect-reviewed drop migration last. Spec: `docs/superpowers/specs/2026-07-04-org-attestor-design.md` — read it before any task.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, pytest(-asyncio), Redis rate limiter, existing Stripe/Paystack payout plumbing.

## Global Constraints

- Backend only. No frontend files. Frontend client regen deferred to the frontend plan.
- Run pytest from `backend/`: `uv run pytest tests -x -q`. **Never run pytest concurrently** (shared dev DB).
- Before claiming any task clean: `uv run ruff check .` (whole repo) and `uv run mypy app` from `backend/`.
- Every migration: `uv run alembic upgrade head` and `uv run alembic downgrade -1` both green. Migration `down_revision` = current head at implementation time (`uv run alembic heads`) — the connectors implementer may be advancing heads in parallel; rebase revision chain, never fork it.
- Coverage ≥80% on touched modules.
- OpenAPI: after each endpoint task, regenerate `contracts/openapi.yaml` from `app.openapi()` using the established regen practice, and validate with `openapi_spec_validator`.
- Commit after each task. Commit messages end at the last meaningful line — **no `Co-Authored-By` trailer**.
- Never log tokens, KYB/tax document keys' presigned URLs, or PII. Reviewing-member identity never appears in public/requestor response schemas.
- RBAC only via FastAPI dependencies (`require_org_role`, `require_org_capability` from `app/modules/organizations/dependencies.py`, platform-admin dep from existing admin module). Never role checks inside services.
- Money paths: all writes inside DB transactions; escrow semantics untouched — only the beneficiary changes.
- Concurrency cap constant stays `DEFAULT_CONCURRENCY_CAP = 5` (`app/modules/attestation/matching_service.py:36`), counted per reviewing member.
- Domain language exact: Attestation, Attestor, Framework, Escrow — never abbreviate.

## Deletion / cutover rules

- Old columns (`attestations.attestor_id`, `attestation_offers.attestor_id`, `attestor_trials.user_id`) and old tables (`attestor_applications`, `attestor_profiles`) are dropped ONLY in Task 13, which requires explicit architect review before merge. Every earlier migration is additive or relax-only (NOT NULL → nullable).
- From Task 6 onward no code path writes the old columns; they exist only for the drop migration to remove.

---

### Task 1: New org-attestor tables + models (migration wave 1)

**Files:**
- Modify: `backend/app/modules/organizations/models.py` (append 3 models)
- Create: `backend/migrations/versions/2026_07_04_00XX_org_attestor_tables.py` (XX = next sequence)
- Test: `backend/tests/unit/modules/test_org_attestor_models.py`

**Interfaces:**
- Produces: `OrgAttestorApplication`, `OrgAttestorProfile`, `OrgMemberNda` SQLAlchemy models importable from `app.modules.organizations.models`.
- Enum values (Python `str` columns with PG enums, matching Org Core style):
  - `ORG_ATTESTOR_APPLICATION_STATUS`: `draft | submitted | needs_info | approved | rejected`

- [ ] **Step 1: Write failing model round-trip tests**

```python
"""Org attestor model persistence tests. Enforces spec data-model section."""
import pytest
from app.modules.organizations.models import (
    OrgAttestorApplication, OrgAttestorProfile, OrgMemberNda,
)

async def test_org_attestor_application_round_trip(db_session, org_factory):
    """Application persists all gate fields; status defaults to draft."""
    org = await org_factory()
    app_row = OrgAttestorApplication(
        org_id=org.id, legal_name="Acme Audit Ltd",
        specializations=["security"], jurisdictions=["US"],
        credentials_summary="ISO auditors", sample_work={"links": []},
        professional_references="refs",
    )
    db_session.add(app_row)
    await db_session.flush()
    assert app_row.status == "draft"
    assert app_row.kyb_verified_at is None
    assert app_row.trial_member_id is None

async def test_one_live_application_per_org(db_session, org_factory):
    """Partial unique index rejects a second draft/submitted/needs_info application."""
    # insert two draft rows for same org -> IntegrityError

async def test_org_member_nda_unique_per_member(db_session, org_member_factory):
    """One NDA signature row per member (re-sign updates version, tested in Task 3)."""
```

Column set for each model — copy exactly from the spec data-model section
(`org_attestor_applications`, `org_attestor_profiles`, `org_member_ndas` blocks),
using the same mixins/types as Org Core models (`CreatedAtMixin`, `UpdatedAtMixin`,
`PG_UUID(as_uuid=True)`, `ARRAY(Text)`, `JSONB`, timestamptz).

- [ ] **Step 2: RED** — `uv run pytest tests/unit/modules/test_org_attestor_models.py -x -q` fails (models undefined).
- [ ] **Step 3: Add the 3 models + migration.** Migration creates the 3 tables, the partial unique index `uq_org_attestor_app_live ON org_attestor_applications(org_id) WHERE status IN ('draft','submitted','needs_info')`, GIN indexes on profile `specializations` and `jurisdictions`, unique on `org_attestor_profiles.org_id` and `org_member_ndas.member_id`. FKs per spec with `ON DELETE CASCADE` on org/member FKs; `trial_attestation_id` FK attestations `ON DELETE SET NULL`; `payout_account_id` FK payout_accounts `ON DELETE SET NULL`. Migration docstring states the WHY + spec reference (project standard).
- [ ] **Step 4: Migration round-trip** — `uv run alembic upgrade head` then `uv run alembic downgrade -1` then `upgrade head` again. All green.
- [ ] **Step 5: GREEN + gates** — model tests pass; `uv run pytest tests -x -q`; ruff + mypy whole repo.
- [ ] **Step 6: Commit** — `Add org attestor application, profile, and member NDA tables`

### Task 2: Re-point columns (migration wave 2, additive)

**Files:**
- Modify: `backend/app/modules/attestation/models.py` (Attestation, AttestationOffer, AttestorTrial: add columns), `backend/app/modules/financials/models.py` (PayoutAccount, Transaction: add columns)
- Create: `backend/migrations/versions/2026_07_04_00XX_org_attestor_repoint_columns.py`
- Test: `backend/tests/unit/modules/test_org_attestor_repoint_models.py`

**Interfaces:**
- Produces (new nullable columns, old columns untouched except NOT NULL relaxed):
  - `Attestation.attestor_org_id: UUID | None` FK organizations, `Attestation.reviewing_member_id: UUID | None` FK org_members; index `idx_attestations_attestor_org_status (attestor_org_id, status)`
  - `AttestationOffer.org_id: UUID | None` FK organizations; unique `uq_attestation_offers_attestation_org (attestation_id, org_id)`; `attestor_id` relaxed to nullable
  - `AttestorTrial.org_id: UUID | None` FK organizations, `AttestorTrial.member_id: UUID | None` FK org_members; `user_id` relaxed to nullable
  - `PayoutAccount.org_id: UUID | None` FK organizations; `user_id` relaxed to nullable; CHECK `ck_payout_accounts_owner_xor ((user_id IS NULL) != (org_id IS NULL))`
  - `Transaction.payee_org_id: UUID | None` FK organizations; CHECK `ck_transactions_single_payee (payee_id IS NULL OR payee_org_id IS NULL)`; index `idx_transactions_payee_org (payee_org_id)`

- [ ] **Step 1: Failing tests** — round-trip each new column; XOR CHECK rejects payout account with both/neither owner; single-payee CHECK rejects transaction with both payees; offer unique on (attestation_id, org_id).
- [ ] **Step 2: RED.**
- [ ] **Step 3: Models + migration.** Additive only; relax NOT NULL via `op.alter_column(..., nullable=True)`. Downgrade restores NOT NULL only if no NULLs would violate (dev DB: acceptable straight restore, document in docstring).
- [ ] **Step 4: Migration round-trip green.**
- [ ] **Step 5: GREEN + full gates.**
- [ ] **Step 6: Commit** — `Add org beneficiary and reviewing-member columns for attestation re-point`

### Task 3: Member NDA mechanics

**Files:**
- Create: `backend/app/modules/organizations/nda_service.py`
- Modify: `backend/app/core/config.py` (add `org_member_nda_version: str = "1.0"`), `backend/app/modules/organizations/router.py`, `backend/app/modules/organizations/schemas.py`, `backend/app/modules/organizations/service.py` (invite-accept signal)
- Test: `backend/tests/unit/modules/test_org_nda_service.py`, `backend/tests/integration/test_org_nda_endpoints.py`

**Interfaces:**
- Produces:
  - `nda_service.get_nda_status(db, *, org_id: UUID, user_id: UUID) -> NdaStatus` — dataclass `NdaStatus(required: bool, current_version: str, signed_version: str | None, signed_at: datetime | None)`. `required` is True iff the org's `attestor` capability status is `pending` or `active`.
  - `nda_service.sign_nda(db, *, org_id: UUID, user_id: UUID) -> OrgMemberNda` — upserts the member's row to the current config version (re-sign after version bump updates `nda_version` + `signed_at`). Commits. Audits `org_nda_signed` (module `organizations`).
  - `nda_service.member_is_assignable(db, *, member_id: UUID) -> bool` — True iff NDA row exists with `nda_version == settings.org_member_nda_version`. Task 6 consumes this.
- Endpoints: `GET /v1/orgs/{org_id}/nda` (member+), `POST /v1/orgs/{org_id}/nda/sign` (member+, rate-limited `RateLimiter(namespace="org_nda_sign", limit=5, window=3600)` per user).
- Invite-accept: `accept_invitation` response schema gains `nda_required: bool` (True when org capability pending/active) so the frontend can chain straight into signing. No behavior change to acceptance itself.

- [ ] **Step 1: Failing unit tests** — status not-required for org without capability row; required for pending and active; sign creates row; re-sign after config version bump replaces version; `member_is_assignable` False for unsigned and stale-version, True for current.
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement service + endpoints + accept signal.**
- [ ] **Step 4: Failing integration tests → implement:** GET/POST happy; 401; 403 non-member; 429 on rate limit; accept-invitation response carries `nda_required`.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add org member NDA signing and assignability checks`

### Task 4: Org attestor application (org side)

**Files:**
- Create: `backend/app/modules/organizations/attestor_application_service.py`, `backend/tests/unit/modules/test_org_attestor_application_service.py`, `backend/tests/integration/test_org_attestor_application_endpoints.py`
- Modify: `backend/app/modules/organizations/router.py`, `backend/app/modules/organizations/schemas.py`

**Interfaces:**
- Produces service functions (all `(db, *, org_id: UUID, actor_id: UUID, ...)`, commit internally, audit each):
  - `create_application(...) -> OrgAttestorApplication` — 409 if a live application exists; org must not already have `attestor` capability active.
  - `get_application(...) -> tuple[OrgAttestorApplication, GateChecklist]` — `GateChecklist` Pydantic model with bool per gate: `kyb_verified, credentials_reviewed, undertakings_signed, payout_account_linked, tax_document_uploaded, trial_passed` (credentials_reviewed = reviewed_at set while status advanced past needs_info; trial_passed = trial attestation closed with passing decision, from Task 5).
  - `update_application(...)` — allowed in `draft`/`needs_info` only, else 409.
  - `submit_application(...)` — Pydantic-complete check (all KYB + matching + credentials fields non-empty), `draft|needs_info → submitted`, else 409. Rate-limited `RateLimiter(namespace="org_attestor_apply", limit=3, window=86400)` per org.
  - `sign_undertakings(db, *, org_id, actor_id, coi_declarations: list[dict], totp_code: str)` — **owner only (dependency), TOTP verified via existing sensitive-action helper**; stamps `coi_signed_at`, `confidentiality_signed_at`, `coi_expires_at = now + existing COI validity period` (reuse the constant the individual flow uses in `application_service.sign_coi`).
  - `attach_payout_account(...)`, `set_tax_document(...)` — mirror individual `attach_payout` / `set_tax_document` semantics (`application_service.py:390,458`) but org-scoped; payout account must be org-owned (`payout_accounts.org_id == org_id`).
  - `nominate_trial_member(db, *, org_id, actor_id, member_id: UUID)` — member must belong to org and pass `nda_service.member_is_assignable`; else 422 `nda_required`.
- Endpoints (org owner/admin; sign-undertakings owner-only): the 7 paths in the spec API-surface block under "Org attestor application".

- [ ] **Step 1: Failing unit tests** — one-live-application 409; update after submit 409; submit incomplete 422; undertakings wrong TOTP 401/422 per existing sensitive-op pattern; nominate unsigned member 422 `nda_required`; gate checklist reflects each stamp.
- [ ] **Step 2: RED.** **Step 3: Implement service.** **Step 4: Failing integration tests → implement router:** each endpoint happy + 401 + 403 (member role, non-member) + suspended org 403; submit rate-limit 429.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add org attestor application flow with gate checklist`

### Task 5: Admin review pipeline + activation

**Files:**
- Modify: `backend/app/modules/organizations/attestor_application_service.py` (admin functions), org router (admin paths) or existing admin router — follow where `list_applications_for_admin` lives today and mirror that placement
- Test: `backend/tests/unit/modules/test_org_attestor_admin_service.py`, `backend/tests/integration/test_org_attestor_admin_endpoints.py`

**Interfaces:**
- Produces (platform-admin only, mirror individual pipeline functions at `application_service.py:558-1025`):
  - `admin_list_applications(db, *, status: str | None, page, page_size)`
  - `admin_verify_kyb(db, *, application_id, admin_id)` — stamps `kyb_verified_at/by`.
  - `admin_needs_info(db, *, application_id, admin_id, feedback: str)` — `submitted → needs_info`.
  - `admin_start_trial(db, *, application_id, admin_id)` — requires nominated trial member; creates trial via existing trial machinery re-keyed to org (`AttestorTrial.org_id` + `member_id` set; `user_id` left NULL); links `trial_attestation_id`.
  - `admin_approve(db, *, application_id, admin_id)` — requires **all** gates (reuse `_missing_activation_prerequisites` pattern, `application_service.py:926`, org edition): kyb, undertakings, payout, tax, trial passed. Then in ONE transaction: application `approved`, create `OrgAttestorProfile` from application fields, upsert `org_capabilities(attestor) = active` + `activated_at`, call `sync_derived_roles` for **every current org member**. Audits `org_attestor_activated`.
  - `admin_reject(db, *, application_id, admin_id, feedback)` — terminal; org may create a new application afterwards.
  - `admin_set_capability_status(db, *, org_id, admin_id, status: Literal["suspended","active","revoked"])` — suspend/reinstate/revoke; suspend/revoke fire `sync_derived_roles` for all members and mark profile `active=False` (revoke) / leave profile but treat as non-matching (suspend — matching filter in Task 6 checks capability status `active`).
- Endpoints: the 7 admin paths in the spec API-surface block.

- [ ] **Step 1: Failing unit tests** — approve blocked listing missing gates (parametrized: each gate absent → 422 naming it); approve creates profile + capability active + derived role granted to every member (assert a plain member now has user-level `attestor` role); reject terminal + reapply allowed; suspend revokes derived roles when it is the member's only attestor org; reinstate re-grants.
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: Integration tests** — each endpoint happy + 401 + 403 non-admin; full gate walk: submit → verify-kyb → sign-undertakings → payout → tax → start-trial → (mark trial passed via test helper) → approve.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add admin review pipeline and org attestor capability activation`

### Task 6: Matching re-point + accept-and-staff

**Files:**
- Modify: `backend/app/modules/attestation/matching_service.py` (bulk of work), `backend/app/modules/attestation/schemas.py`, `backend/app/modules/attestation/router.py`, `backend/app/modules/attestation/notifications.py`
- Test: extend `backend/tests/unit/modules/test_attestation_matching_service.py` + `backend/tests/integration/test_attestation_matching_endpoints.py` (follow existing file names if they differ — locate with `grep -rl offer_next_cohort backend/tests`)

**Interfaces:**
- Re-pointed behavior (function names unchanged where possible so callers stay stable):
  - `offer_next_cohort` ranks `OrgAttestorProfile` rows where org capability status is `active` and profile `active=True`. Offer rows write `org_id` (never `attestor_id`). Offer notifications to org owner + admins.
  - COI screen (`_is_coi_conflicted` + exclusion set): existing declaration screening against org `coi_declarations`, PLUS exclude orgs where the requestor is a member, PLUS orgs where the attestation target framework's owner is a member.
  - `accept_attestation_offer(db, *, offer_id: UUID, org_id: UUID, actor_id: UUID, reviewing_member_id: UUID)` — actor must be org owner/admin (router dependency); validates member belongs to org (404), `nda_service.member_is_assignable` (422 `nda_required`), `_active_assignment_count` re-keyed to count attestations by `reviewing_member_id` `< DEFAULT_CONCURRENCY_CAP` (422 `member_at_capacity`). Sets `attestations.attestor_org_id + reviewing_member_id`, keeps existing status/SLA mechanics.
  - `decline_attestation_offer` org-scoped; `expire_stale_offers` unchanged mechanics.
  - Offer accept/decline while org `attestor` capability is `suspended`/`revoked` → 403 `capability_suspended` (list stays readable).
  - COI renewal machinery re-pointed: `send_coi_resign_reminders` (`matching_service.py:550`) and `expire_owner_consent` read/write `OrgAttestorProfile` COI fields; reminder notifications go to org owner + admins.
  - New `reassign_reviewing_member(db, *, attestation_id, org_id, actor_id, reviewing_member_id)` — allowed only while `review_started_at IS NULL` (409 after); same member validations; audited `attestation_reviewer_reassigned`.
  - Member-removal blocker: extend `organizations/service.py:remove_member` — member with started in-flight reviews → 409; unstarted assignments get `reviewing_member_id=NULL` (org must restaff via reassign) and audit.
- Endpoints: the 4 offer/staffing paths in the spec API-surface block + `GET /v1/orgs/{org_id}/attestations` (owner/admin: all org attestations; plain member: only rows where they are the reviewing member).

- [ ] **Step 1: Failing unit tests** — cohort ranks only active-capability orgs; suspended capability excluded; requestor-member org excluded; member-owned-target org excluded; accept validations (non-member 404, unsigned NDA 422 `nda_required`, at-cap 422 `member_at_capacity`); accept sets both new columns and never writes `attestor_id`; accept under suspended capability 403 `capability_suspended`; COI reminder targets org profile fields; reassign before start OK / after start 409; remove_member with started review 409, with unstarted assignment nulls reviewer.
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: Integration tests** — accept/decline/reassign/org-queue endpoints: happy + 401 + 403 (plain member calling accept) + org-mismatch 404.
- [ ] **Step 5: GREEN + full suite (expect and fix fallout in tests still building individual attestors — update fixtures/factories to org attestors here) + gates + contract regen.**
- [ ] **Step 6: Commit** — `Re-point attestation matching to orgs with accept-and-staff`

### Task 7: Workspace + delivery guards re-point

**Files:**
- Modify: `backend/app/modules/attestation/workspace_service.py`, `clarification_service.py`, `document_service.py`, `report.py`, `access_service.py`, `service.py`, `dispute_service.py`, `release_service.py` (guard sites only), `dependencies.py`
- Test: extend the corresponding existing unit/integration test files (locate per service with grep)

**Interfaces:**
- Guard rule everywhere the old code compared `attestation.attestor_id == user.id`: reviewing member (user behind `reviewing_member_id`) gets **write** access (rubric scores, annotations, clarifications, uploads, report submission, content-ack); org owner/admins of `attestor_org_id` get **read** access on those surfaces; requestor-facing behavior unchanged. Provide one shared helper in `attestation/dependencies.py`:
  - `resolve_attestor_actor(db, *, attestation, user) -> AttestorActor` — dataclass `AttestorActor(is_reviewing_member: bool, is_org_manager: bool, member_id: UUID | None)`; 403 when neither.
- Late-submission and SLA bookkeeping (`late_submission_count`, `suspension_review_at`) move to `OrgAttestorProfile`.
- Dispute records keep reviewing-member identity in their internal payloads (admin/dispute views) — this is the sanctioned internal exposure.

- [ ] **Step 1: Failing tests** — reviewing member can score/annotate/upload/submit; org admin read-only (403 on writes); unrelated org member 403; requestor path untouched (existing tests keep passing); late submission increments org profile counter.
- [ ] **Step 2: RED.** **Step 3: Implement helper + sweep guard sites** (grep `attestor_id` per file; every site either uses the helper or is a data re-point).
- [ ] **Step 4: GREEN + full suite + gates.**
- [ ] **Step 5: Commit** — `Re-point attestation workspace and delivery guards to reviewing members`

### Task 8: Settlement, org financials, invoicing

**Files:**
- Modify: `backend/app/modules/attestation/release_service.py`, `backend/app/modules/financials/service.py`, `escrow_service.py` (payee handling), `invoices.py`, `backend/app/modules/invoicing/annual.py`, `backend/app/workers/tasks/invoicing_beat.py`, org router (financials paths)
- Test: extend financials/attestation settlement test files + `backend/tests/integration/test_org_financials_endpoints.py`

**Interfaces:**
- Settlement: attestation escrow release writes the 90% attestor-share transaction with `payee_org_id = attestation.attestor_org_id`, `payee_id = NULL`. Split/commission math untouched.
- `onboard_org_payout_account(db, *, org_id, actor_id, ...)` — wraps existing `onboard_payout_account` plumbing (`financials/service.py:1503`) with `payout_accounts.org_id` ownership and provider routing on **org** `country` (`select_provider`).
- `request_org_payout(db, *, org_id, actor_id, totp_code, amount, currency)` — org owner/admin; TOTP of the **actor**; gates: org payout account exists AND org has an `approved` `OrgAttestorApplication` (KYB stands in for KYC) — else 403; balance = sum of org-payee completed transactions minus claimed payouts (mirror `_available_payout_balance` with org key).
- `list_org_earnings`, `list_org_invoices` read endpoints (owner/admin).
- Invoices render org `legal_name` (+ tax data from application); annual invoicing beat iterates org identities for org-attested work.
- Endpoints: the 4 financials paths in the spec API-surface block.

- [ ] **Step 1: Failing unit tests** — release credits `payee_org_id` and not `payee_id`; payout gates (no account 403, no approved application 403, wrong TOTP rejected); balance excludes user-payee transactions; invoice carries org legal name.
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: Integration tests** — endpoints happy + 401 + 403 (plain member) + PII rule: payout account details never in list payloads.
- [ ] **Step 5: GREEN + full suite + gates + contract regen.**
- [ ] **Step 6: Commit** — `Route attestation settlement and payouts to organizations`

### Task 9: Badge, provenance, directory, public surfaces

**Files:**
- Modify: `backend/app/modules/attestation/badge_service.py`, `certification_service.py`, `directory_service.py`, `backend/app/modules/explore/service.py` + `schemas.py`, `backend/app/modules/profiles/service.py`, `backend/app/workers/tasks/attestation_pdf.py`
- Test: extend badge/directory/explore test files; add `backend/tests/unit/modules/test_attestor_identity_privacy.py`

**Interfaces:**
- `publish_badge` snapshots org identity at issuance: org `name`, `slug`, profile `verification_level` into the badge row's identity fields (rename columns/fields if they were user-named; keep public payload keys the contract already exposes where possible, values become org).
- Public badge JSON, provenance endpoints, explore attestation surfaces: org identity only. Platform-admin provenance view additionally includes reviewing member.
- `certification_service.evaluate_attestor_certification` re-keyed to `OrgAttestorProfile.certified_attestor_at` (same never-clear recompute rule).
- Directory: `list_directory`/`get_directory_profile` list attestor **orgs** — profile fields, completed count, certification mark, member count; no member identities. `_completed_attestations` keys on `attestor_org_id`.
- Profiles module: drop individual attestor advertisement from public user profiles.
- **Privacy test (schema-level):** for every public/requestor-facing attestation response schema, assert `reviewing_member_id`/member identity fields are absent (introspect Pydantic model fields; leakage here is a review blocker per spec).

- [ ] **Step 1: Failing tests** — badge snapshot org fields; badge survives org rename (snapshot, not join); directory lists orgs with counts; explore shows org identity; privacy schema test; certification stamps org profile.
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: GREEN + full suite + gates + contract regen.**
- [ ] **Step 5: Commit** — `Present org identity on badges, provenance, and attestor directory`

### Task 10: Ratings, warnings, reputation, GDPR

**Files:**
- Modify: `backend/app/modules/attestation/rating_service.py`, models (rating/warning re-point already columned via usage of `attestor_org_id` from attestation row — verify; add org FK columns here in a small additive migration ONLY if ratings/warnings carry their own attestor column), `backend/app/modules/reputation/factors.py`, `backend/app/workers/tasks/reputation.py`, `backend/app/modules/gdpr/export_service.py`, `deletion_service.py`
- Test: extend corresponding test files

**Interfaces:**
- Ratings and warnings attach to the org (rated/warned party = `attestor_org_id`). Check `attestation_ratings` / `attestor_warnings` schemas: if they carry `attestor_id` columns, add `org_id` in an additive migration in this task and stop writing the old column.
- Reputation factors that consumed individual attestor signals consume org-level signals (org completed attestations, org ratings). User-level reputation no longer gains attestor factors.
- GDPR export (user): + NDA signatures, + reviewing-member assignment history (attestation ids + dates only). Org attestor application data is NOT in user export (org-owned; exported via org owner request path if/when org export exists — out of scope beyond excluding it here).
- GDPR deletion: user with a started in-flight review as reviewing member → deletion blocked (extend `user_deletion_org_blockers` / existing obligations pattern).

- [ ] **Step 1: Failing tests** — rating lands on org; warning lands on org; reputation factor reads org signals; export contains NDA + assignments, not org application; deletion blocked for active reviewing member, allowed after resolution.
- [ ] **Step 2: RED.** **Step 3: Implement (+ additive migration if needed, round-trip tested).** **Step 4: GREEN + full suite + gates.**
- [ ] **Step 5: Commit** — `Re-point ratings, warnings, reputation, and GDPR to org attestors`

### Task 11: Full lifecycle integration test

**Files:**
- Create: `backend/tests/integration/test_org_attestor_lifecycle.py`

One end-to-end test through real endpoints (existing fixtures/factories): create org → invite + accept member (NDA signed) → application create/submit → admin KYB → owner signs undertakings (TOTP) → org payout account → tax doc → nominate trial member → admin start-trial + pass → admin approve (capability active, member gains derived attestor role) → requestor funds attestation → offer to org → admin accept-and-staff → reviewing member acks + scores + submits report → requestor accepts → escrow release credits org → org earnings visible → org payout request succeeds → badge shows org identity → directory lists org.

- [ ] **Step 1: Write the test (RED where any seam is missing — fix the seam, not the test).**
- [ ] **Step 2: GREEN + full suite + gates.**
- [ ] **Step 3: Commit** — `Add org attestor end-to-end lifecycle test`

### Task 12: Individual attestor retirement + contract regen

**Files:**
- Modify: `backend/app/modules/auth/` role-selection validation (registration + `POST /v1/auth/roles` reject `attestor`), `backend/app/modules/attestation/router.py` (remove individual application/profile endpoints), `backend/app/modules/attestation/application_service.py` (delete retired functions), `contracts/openapi.yaml` (regen)
- Test: extend auth role tests + `backend/tests/integration/test_attestation_retirement.py`

**Interfaces:**
- `attestor` rejected at self-selection with 422 (message: attestor access comes via organizations). Derived role via `sync_derived_roles` is the only grant path. `require_role("attestor")` guards untouched.
- Individual application/COI/tax/trial-nomination endpoints removed from router; removed paths return 404. Credential endpoints (user-owned `credentials`) SURVIVE.
- Dead code deleted (retired service functions, schemas); imports clean.
- Full contract regen from `app.openapi()`, validated with `openapi_spec_validator`; diff shows removed individual paths + all new org paths.

- [ ] **Step 1: Failing tests** — role selection rejects attestor (register + roles endpoints); removed paths 404; credentials endpoints still 2xx; derived-role path still grants.
- [ ] **Step 2: RED.** **Step 3: Implement removals.** **Step 4: GREEN + full suite + whole-repo ruff/mypy (dead-import sweep) + contract regen/validate.**
- [ ] **Step 5: Commit** — `Retire individual attestor pipeline; attestor role is org-derived only`

### Task 13: Final drop migration — ⚠️ ARCHITECT REVIEW REQUIRED

**Files:**
- Create: `backend/migrations/versions/2026_07_XX_00XX_drop_individual_attestor_structures.py`
- Test: migration round-trip + `backend/tests/integration/test_org_attestor_lifecycle.py` re-run

Drops: tables `attestor_applications`, `attestor_profiles`; columns `attestations.attestor_id`, `attestation_offers.attestor_id` (+ old unique `uq_attestation_offers_attestation_attestor`, old index `idx_attestations_attestor_status`), `attestor_trials.user_id`. Downgrade recreates structures empty (document irreversibility of data in docstring).

- [ ] **Step 1: Grep gate** — `grep -rn "attestor_id" backend/app | grep -v attestor_org_id` returns ZERO hits before writing the migration (code no longer references old columns). Same for `attestor_applications`, `AttestorProfile`.
- [ ] **Step 2: Write migration. STOP — present the migration file to the architect for explicit review/approval before running it** (CLAUDE.md: drops require human review). Do not proceed on silence.
- [ ] **Step 3: After approval:** round-trip green, full suite green, gates green.
- [ ] **Step 4: Commit** — `Drop retired individual attestor tables and columns`

---

## Verification (whole plan)

- `uv run pytest tests -x -q` green from `backend/`; coverage ≥80% touched modules.
- `uv run ruff check .` + `uv run mypy app` clean (whole repo).
- `uv run alembic upgrade head` from scratch DB green; every migration downgrade-tested.
- Contract: no individual attestor paths; all spec API-surface paths present; validator green.
- Security greps: reviewing-member absent from public schemas (Task 9 test), no token/PII logging introduced (`grep -rn "logger" over new files` reviewed), RBAC via dependencies only.

## Risks

- **Breadth of re-point (16 attestation files + 6 modules + 3 workers):** Tasks 6–10 slice by service; full suite runs every task; Task 13 grep gate proves completeness.
- **Money-path schema change (Task 2, Task 8):** XOR/CHECK constraints enforce single beneficiary at the DB; escrow release logic untouched except payee fields; architect attention flagged on both tasks' reviews.
- **Parallel connectors implementer advancing migration heads:** every migration takes `alembic heads` at implementation time; conflicts resolved by chaining, never branching.
- **Drop migration:** Task 13 hard-stops for architect approval.
