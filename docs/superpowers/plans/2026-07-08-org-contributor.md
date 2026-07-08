# Organizations as Contributors (Sub-project 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `contributor` org capability real end-to-end — self-activation → members author Frameworks under org identity → owners/admins publish and sell → org bids on and delivers Projects → org settlement/payout/invoicing → org public identity — additively, without retiring individual contributors.

**Architecture:** Additive. Supply-side ownable entities (`frameworks`, `proposals`, `deliverables`) become ownable by a user **or** an org via the XOR pattern already shipped on `payout_accounts`/`transactions`. New contributor tables + shared legal identity live in `app/modules/organizations/`; frameworks/projects services gain an org-owner path; financials reuses the org beneficiary plumbing built for attestor. No drop migrations — every migration is additive or relax-only. Spec: `docs/superpowers/specs/2026-07-08-org-contributor-design.md` — read it before any task.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, pytest(-asyncio) + httpx AsyncClient, Redis rate limiter, existing Stripe/Paystack payout plumbing.

## Global Constraints

- Backend only. No frontend files. Frontend client regen deferred to a separate frontend plan.
- Run pytest from `backend/`: `uv run pytest tests -x -q`. **Never run pytest concurrently** (shared dev DB).
- Before claiming any task clean: `uv run ruff check .` (whole repo) and `uv run mypy app` from `backend/`.
- Every migration: `uv run alembic upgrade head` and `uv run alembic downgrade -1` both green, then `upgrade head` again. Migration `down_revision` = current head at implementation time (`uv run alembic heads`) — never fork the revision chain, rebase it.
- Coverage ≥80% on touched modules.
- OpenAPI: after each endpoint task, regenerate `contracts/openapi.yaml` from `app.openapi()` using the established regen practice, and validate with `openapi_spec_validator`.
- Commit after each task. Commit messages end at the last meaningful line — **no `Co-Authored-By` trailer**. Work on `main`.
- RBAC only via FastAPI dependencies (`require_org_role`, `require_org_capability` from `app/modules/organizations/dependencies.py`; platform-admin dep from the existing admin module). **Never** role checks inside services.
- Money paths: all writes inside DB transactions; escrow semantics untouched — only the beneficiary changes. Never log tokens, payout-account details, tax-document keys' presigned URLs, or PII.
- Provenance confidentiality: `authoring_member_id` / `delivering_member_id` (and any member identity) NEVER appear in public / buyer / operator response schemas. Leakage is a review blocker.
- Domain language exact: Framework, Artifact, License, Project, Proposal, Milestone, Deliverable, Escrow, Contributor, Operator — never abbreviate.

## Additive-only rules

- No column or table is dropped in this sub-project. `contributor_id` on `frameworks`/`proposals`/`deliverables` is relaxed NOT NULL → nullable and coexists with the new `contributor_org_id`; individual rows keep using `contributor_id`.
- Every XOR is a DB `CHECK ((user_col IS NULL) != (org_col IS NULL))`; individual paths keep writing the user column, org paths write the org column.

---

### Task 1: Contributor capability foundation (tables + role marker + generalized derived-role sync)

**Files:**
- Modify: `backend/app/modules/organizations/models.py` (append 2 models), `backend/app/modules/auth/models.py` (`UserRole.source` column), `backend/app/modules/organizations/service.py` (`sync_derived_roles`)
- Create: `backend/migrations/versions/2026_07_08_00XX_org_contributor_foundation.py`
- Test: `backend/tests/unit/modules/test_org_contributor_models.py`, extend `backend/tests/unit/modules/test_org_derived_roles.py` (locate the existing sync test with `grep -rl sync_derived_roles backend/tests`; create the file if none exists)

**Interfaces:**
- Produces `OrgContributorProfile`, `OrgLegalProfile` importable from `app.modules.organizations.models`. Columns copied exactly from the spec data-model blocks (`org_contributor_profiles`, `org_legal_profiles`), same mixins/types as Org Core models (`UpdatedAtMixin`, `PG_UUID(as_uuid=True)`, `JSONB`, `Numeric`, timestamptz). Both: `org_id` FK organizations `ON DELETE CASCADE`, unique.
- Produces `UserRole.source: str | None` (`'self'` | `'derived'`).
- Re-shapes `sync_derived_roles(db, *, user_id)` from attestor-only to a capability→role map: `_DERIVED_ROLE_MAP = {"attestor": "attestor", "contributor": "contributor"}`. For each `(capability, role)`: `should_have` = user belongs to ≥1 live (not suspended/deactivated) org whose capability is `active`; grant creates `UserRole(role=role, source="derived", approved_at=now)`; revoke deletes ONLY the row where `role == role AND source == "derived"`. **A `source="self"` row is never granted, touched, or deleted here.** Idempotent.

- [ ] **Step 1: Failing unit tests** — (a) `OrgContributorProfile`/`OrgLegalProfile` round-trip; profile `active` defaults true, `verification_level` defaults 1. (b) `sync_derived_roles` grants a `source="derived"` `contributor` role when the user is in an org with `contributor` capability active. (c) a pre-existing `source="self"` `contributor` role is left intact when the user is in NO active-contributor org (sync must not delete it). (d) attestor derived-role behavior still works (regression).
- [ ] **Step 2: RED** — `uv run pytest tests/unit/modules/test_org_contributor_models.py tests/unit/modules/test_org_derived_roles.py -x -q` fails.
- [ ] **Step 3: Add models + `UserRole.source` + rewrite `sync_derived_roles`.** Migration: create both tables (unique on `org_id`); add `user_roles.source` (nullable text); backfill existing rows — `UPDATE user_roles SET source='derived' WHERE role='attestor'` (attestor is org-derived-only post sub-project 2), `SET source='self'` for all other roles. Migration docstring states the WHY + spec reference.
- [ ] **Step 4: Migration round-trip** green (up / down / up).
- [ ] **Step 5: GREEN + gates** — full suite; `uv run ruff check .`; `uv run mypy app`.
- [ ] **Step 6: Commit** — `Add org contributor foundation tables and generalize derived-role sync`

### Task 2: Framework XOR ownership + seller resolution

**Files:**
- Modify: `backend/app/modules/frameworks/models.py` (Framework: add columns, relax `contributor_id`)
- Create: `backend/migrations/versions/2026_07_08_00XX_framework_org_ownership.py`, `backend/app/modules/frameworks/ownership.py` (seller resolution helper), `backend/tests/unit/modules/test_framework_ownership.py`

**Interfaces:**
- Produces new nullable columns on `frameworks`: `contributor_org_id UUID FK organizations` (index `idx_frameworks_contributor_org_status (contributor_org_id, status)`); `authoring_member_id UUID FK org_members ON DELETE SET NULL`; `contributor_id` relaxed to nullable; CHECK `ck_frameworks_seller_xor ((contributor_id IS NULL) != (contributor_org_id IS NULL))`.
- Produces `ownership.resolve_framework_seller(framework) -> FrameworkSeller` — dataclass `FrameworkSeller(kind: Literal["user","org"], user_id: UUID | None, org_id: UUID | None)`; reads whichever of the two columns is set. Consumed by every later task that needs "who sells this framework".

- [ ] **Step 1: Failing tests** — XOR CHECK rejects a framework with both seller columns set and with neither; `resolve_framework_seller` returns `kind="org"` when `contributor_org_id` set, `kind="user"` otherwise.
- [ ] **Step 2: RED.**
- [ ] **Step 3: Models + migration + helper.** Additive; relax `contributor_id` NOT NULL via `op.alter_column(..., nullable=True)`; downgrade restores NOT NULL (dev DB straight restore, documented).
- [ ] **Step 4: Migration round-trip green.**
- [ ] **Step 5: GREEN + full gates.**
- [ ] **Step 6: Commit** — `Add framework org ownership columns and seller resolution`

### Task 3: Contributor capability activation + suspension

**Files:**
- Create: `backend/app/modules/organizations/contributor_service.py`, `backend/tests/unit/modules/test_org_contributor_capability.py`, `backend/tests/integration/test_org_contributor_capability_endpoints.py`
- Modify: `backend/app/modules/organizations/router.py`, `backend/app/modules/organizations/schemas.py`

**Interfaces:**
- Produces (commit internally, audit each; `module="organizations"`):
  - `activate_contributor_capability(db, *, org_id, actor_id) -> OrgCapability` — org not suspended/deactivated; upserts `org_capabilities(contributor) = active` + `activated_at`; creates `OrgContributorProfile` (active=true) if absent; calls `sync_derived_roles` for **every current org member**. Idempotent (already-active → 200, no duplicate profile). Audits `org_contributor_activated`.
  - `admin_set_contributor_capability_status(db, *, org_id, admin_id, status: Literal["suspended","active","revoked"])` — platform-admin; sets status; `suspended`/`revoked` fire `sync_derived_roles` for all members and (revoke) set profile `active=False`; audits `org_contributor_capability_status_changed`.
  - `contributor_capability_active(db, *, org_id) -> bool` — helper reused by later publish/proposal/payout gates (True iff capability row `active`).
- Endpoints: `POST /v1/orgs/{org_id}/contributor-capability/activate` (`require_org_role("admin")`, rate-limited `RateLimiter(namespace="org_contributor_activate", limit=5, window=3600)` per org); `POST /v1/admin/orgs/{org_id}/contributor-capability/{suspend|reinstate|revoke}` (platform-admin dep).

- [ ] **Step 1: Failing unit tests** — activate creates capability active + profile + grants derived `contributor` role to a plain member (assert the member now has a `source="derived"` contributor `UserRole`); activate on suspended org raises 403 (via dependency, tested at endpoint) — unit tests the service precondition path; idempotent re-activate no dup profile; admin suspend revokes derived role when it is the member's only contributor org; reinstate re-grants; revoke sets profile inactive.
- [ ] **Step 2: RED.** **Step 3: Implement service + endpoints.** **Step 4: Failing integration tests → implement:** activate happy + 401 + 403 (plain member) + 403 suspended org; admin suspend/reinstate/revoke happy + 401 + 403 non-admin.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add contributor capability self-activation and admin suspension`

### Task 4: Org framework authoring + publish

**Files:**
- Modify: `backend/app/modules/frameworks/service.py` (thread an org-owner context through create + gate live-state ops on the resolved seller), `backend/app/modules/frameworks/router.py`, `backend/app/modules/frameworks/schemas.py`
- Test: `backend/tests/unit/modules/test_org_framework_service.py`, `backend/tests/integration/test_org_framework_endpoints.py`

**Interfaces:**
- Org-scoped routes on the frameworks router, all under `require_org_capability("contributor")`:
  - create/edit/artifact upload+confirm/submit → `require_org_role("member")`
  - publish/unpublish/version/pricing → `require_org_role("admin")`
  - list/detail → `require_org_role("member")` (owner/admin get full, plain member read)
  - Paths per the spec "Framework authoring & publish flow" block.
- Create stamps `contributor_org_id = org_id`, `contributor_id = NULL`, `authoring_member_id = <caller OrgMember.id>`. Existing individual create path (`/v1/frameworks`) unchanged — it stamps `contributor_id`, leaves org columns NULL.
- The existing service functions take a seller context. Introduce a small internal owner descriptor rather than duplicating logic: e.g. `create_framework(db, *, owner: FrameworkOwner, ...)` where `FrameworkOwner` is `{user_id}` or `{org_id, authoring_member_id}`; ownership checks in edit/publish resolve via `ownership.resolve_framework_seller` and compare against the org context. Do NOT fork the publish pipeline — reuse `submit`/publish logic; only the ownership guard + stamp differ.
- Publish precondition: `contributor_capability_active(org_id)` True (else 403 `capability_suspended`) + framework `pipeline_passed`. No payout readiness at publish. Content pipeline unchanged.

- [ ] **Step 1: Failing unit tests** — org create stamps org+authoring_member, NULL contributor_id; plain member can create/edit/submit; publish by member forbidden path (service-level ownership guard) while admin allowed; publish while capability suspended → 403 `capability_suspended`; individual create path still stamps contributor_id only (regression).
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: Failing integration tests → implement router:** each org route happy + 401 + 403 (wrong org role: member on publish, non-member on anything) + 403 capability inactive; cross-org detail 404.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add org framework authoring and admin-gated publish`

### Task 5: Public surfaces — seller identity, suspension hiding, directory, privacy

**Files:**
- Modify: `backend/app/modules/explore/service.py` + `schemas.py` (seller card resolution + hide suspended-org frameworks), `backend/app/modules/frameworks/schemas.py` (detail seller identity)
- Create: `backend/app/modules/organizations/contributor_directory_service.py`, directory endpoints on the org/public router, `backend/tests/unit/modules/test_org_contributor_directory.py`, `backend/tests/integration/test_org_contributor_public.py`, `backend/tests/unit/modules/test_contributor_identity_privacy.py`

**Interfaces:**
- Explore + framework detail seller card resolves via `resolve_framework_seller`: org → org `name`/`slug`/`verification_level`/reputation; user → existing individual identity. `authoring_member_id` never in these payloads.
- Frameworks whose `contributor_org_id` points at an org with `contributor` capability NOT `active` are excluded from Explore listing (treated unlisted); existing licenses still resolve for current buyers (detail fetch by a licensed operator still allowed).
- `contributor_directory_service.list_contributor_orgs(...)` / `get_contributor_org(slug)` — list contributor **orgs**: profile fields, published framework count, reputation, verification mark, member count (no member identities). Endpoints `GET /v1/contributors`, `GET /v1/contributors/{org_slug}`.
- Privacy test (schema-level): for every public/buyer/operator-facing framework/explore/directory response schema, assert `authoring_member_id` / member-identity fields are absent (introspect Pydantic model fields).

- [ ] **Step 1: Failing tests** — explore seller card shows org identity for org framework, individual for user framework; suspended-contributor-org framework absent from explore list but licensed-operator detail still resolves; directory lists orgs with counts and no member identities; privacy schema test.
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: GREEN + full gates + contract regen.**
- [ ] **Step 5: Commit** — `Present org contributor identity on explore, detail, and directory`

### Task 6: Projects — XOR ownership + org bid, staff, deliver

**Files:**
- Modify: `backend/app/modules/projects/models.py` (Proposal, Deliverable: add columns, relax `contributor_id`), `backend/app/modules/projects/service.py`, `backend/app/modules/projects/router.py`, `backend/app/modules/projects/schemas.py`, `backend/app/modules/organizations/service.py` (`remove_member` blocker extension)
- Create: `backend/migrations/versions/2026_07_08_00XX_project_org_ownership.py`, `backend/tests/unit/modules/test_org_proposal_service.py`, `backend/tests/integration/test_org_proposal_endpoints.py`

**Interfaces:**
- Migration (additive/relax): `proposals` + `contributor_org_id UUID FK organizations`, `+ delivering_member_id UUID FK org_members ON DELETE SET NULL`, relax `contributor_id` nullable, CHECK `ck_proposals_seller_xor`, partial-unique `uq_proposals_project_org_active (project_id, contributor_org_id) WHERE status IN ('pending','accepted')`. `deliverables` + `contributor_org_id UUID FK organizations`, relax `contributor_id` nullable, CHECK `ck_deliverables_seller_xor`.
- Service (org owner/admin; commit + audit; `module="projects"`):
  - `submit_org_proposal(db, *, org_id, actor_id, project_id, delivering_member_id, scope, budget, timeline_days, deliverables)` — capability active (403 `capability_suspended`); one live org proposal per project (409); member belongs to org (422); **self-deal COI**: 422 `self_deal_conflict` when the project's `operator_id` is a member of this org. Stamps `contributor_org_id`, `delivering_member_id`, NULL `contributor_id`.
  - `withdraw_org_proposal(...)` — owner/admin.
  - `reassign_delivering_member(db, *, org_id, actor_id, proposal_id, delivering_member_id)` — allowed only while no deliverable work has started (define "started" as the accepted proposal having ≥1 milestone with status past `pending`/funded work begun — mirror the attestor `review_started_at` window; locate the equivalent project signal); after start → 409. Audited.
  - Deliverable submission for org-owned work: only the `delivering_member_id` may submit (workspace guard); deliverable stamped `contributor_org_id`. Owner/admin read.
  - `remove_member` extension: member with a started, unfinished org delivery → 409 blocked; with only unstarted assignment → clear `delivering_member_id` (org must restaff) + audit.
- Endpoints: the org proposal/deliveries paths in the spec API-surface block.

- [ ] **Step 1: Failing unit tests** — XOR checks on proposal + deliverable; one-org-proposal-per-project 409; self-deal COI 422; non-member delivering_member 422; reassign before start OK / after start 409; deliverable submit by non-delivering member forbidden; remove_member blocked on started delivery, nulls reviewer on unstarted; capability suspended blocks new proposal.
- [ ] **Step 2: RED.** **Step 3: Migration + models + service.** **Step 4: Failing integration tests → implement router:** submit/withdraw/reassign/deliveries endpoints happy + 401 + 403 (plain member on submit/reassign) + 403 suspended; migration round-trip green.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add org project bidding, member staffing, and delivery`

### Task 7: Settlement, org financials, shared legal identity, invoicing

**Files:**
- Modify: `backend/app/modules/financials/service.py` (framework-sale payee resolution ~`service.py:856,916`; contributor org payout gate), `backend/app/modules/financials/escrow_service.py` (milestone-release payee for org sellers), `backend/app/modules/financials/invoices.py`, `backend/app/modules/organizations/router.py` + `schemas.py` (legal-profile endpoints)
- Create: `backend/app/modules/organizations/legal_profile_service.py`, `backend/tests/unit/modules/test_org_contributor_settlement.py`, `backend/tests/integration/test_org_contributor_financials.py`

**Interfaces:**
- Settlement re-point: where a framework sale settles to the contributor (`financials/service.py:856` resolves `framework.contributor_id` → payee), resolve via `resolve_framework_seller`: org seller → transaction `payee_org_id = org_id`, `payee_id = NULL`; user seller unchanged. Same for project milestone release when the accepted proposal is org-owned → `payee_org_id`. Split/commission math untouched.
- Org contributor payout gate: reuse shipped `request_org_payout` (`financials/service.py:1693`) but the contributor eligibility key is **payout account present + tax document on file + capability active** (NOT an approved application — that is the attestor key). If `request_org_payout`'s gate is attestor-specific, parametrize it by capability so a contributor org qualifies via the tax-doc/account path; keep the attestor path intact.
- `legal_profile_service`: `get_legal_profile`, `upsert_legal_profile(db, *, org_id, actor_id, totp_code, legal_name, registration_number, address)` — **owner only + TOTP** (existing sensitive-action helper); `set_legal_tax_document(...)` upload ticket. Backs `org_legal_profiles`.
- Invoicing reads legal identity from `org_legal_profiles`; re-point attestor invoicing to read the same shared row (backward-compatible — attestor application keeps KYB verification stamps; only the rendered legal_name/address/tax source moves). Flag this change explicitly in the task's review.
- Earnings read: reuse the shipped org earnings/`list_org_invoices` endpoints (they filter by `payee_org_id`, source-agnostic — contributor earnings appear automatically). Endpoints: `GET/PUT /v1/orgs/{org_id}/legal-profile`, `POST /v1/orgs/{org_id}/legal-profile/tax-document`; financials paths reuse existing org routes.

- [ ] **Step 1: Failing unit tests** — framework sale by org seller credits `payee_org_id`, not `payee_id`; milestone release for org proposal credits `payee_org_id`; individual seller path unchanged (regression); contributor org payout allowed with account+tax+active, blocked (403) without tax doc; legal-profile upsert requires owner + TOTP; invoice for org sale renders `org_legal_profiles.legal_name`; attestor invoice still renders correct legal name after re-point.
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: Failing integration tests → implement:** legal-profile endpoints happy + 401 + 403 (admin, not owner) + wrong-TOTP; payout happy + gate 403s; PII rule — tax-doc key / payout-account details never in list payloads.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Route contributor settlement and payouts to organizations with shared legal identity`

### Task 8: Reputation + GDPR

**Files:**
- Modify: `backend/app/modules/reputation/factors.py` (or the reputation module's factor file — locate with `grep -rln contributor backend/app/modules/reputation`), `backend/app/workers/tasks/reputation.py`, `backend/app/modules/gdpr/export_service.py`, `backend/app/modules/gdpr/deletion_service.py`
- Test: extend the corresponding reputation + GDPR test files

**Interfaces:**
- Org contributor reputation: the recompute worker aggregates the org's published-framework `reviews` (score) + a completed-project signal into `OrgContributorProfile.reputation_score`, keyed on `contributor_org_id`. Individual members' personal reputation is untouched.
- GDPR export (user): include the user's org authoring history (framework ids they authored as `authoring_member_id`) and delivery history (proposals/deliverables where they were `delivering_member_id`) — ids + dates only. Org-owned framework/earnings data is NOT in the user export (org-owned).
- GDPR deletion: a user with a started, unfinished org delivery as `delivering_member_id` → deletion blocked (extend the existing org-obligation blocker used for attestor reviewing members).

- [ ] **Step 1: Failing tests** — reputation aggregates an org's framework reviews into the org profile; export contains authoring/delivery ids, not org earnings; deletion blocked for a member mid-delivery, allowed after resolution.
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: GREEN + full gates.**
- [ ] **Step 5: Commit** — `Add org contributor reputation and GDPR touchpoints`

### Task 9: Full lifecycle integration test

**Files:**
- Create: `backend/tests/integration/test_org_contributor_lifecycle.py`

One end-to-end test through real endpoints (existing fixtures/factories): create org → activate contributor capability (member gains derived contributor role) → member authors a framework + uploads artifact + submits pipeline → admin publishes → operator purchases → escrow settles to org (`payee_org_id`) → org earnings visible → set legal profile (owner + TOTP) → org payout account → tax doc → org payout request succeeds → explore/detail show org identity, author hidden → directory lists the org. Then the project path: operator posts project → org submits proposal (delivering member) → operator accepts → delivering member submits deliverable → milestone approved → release credits org.

- [ ] **Step 1: Write the test (RED where any seam is missing — fix the seam, not the test).**
- [ ] **Step 2: GREEN + full suite + gates.**
- [ ] **Step 3: Commit** — `Add org contributor end-to-end lifecycle test`

---

## Verification (whole plan)

- `uv run pytest tests -x -q` green from `backend/`; coverage ≥80% touched modules.
- `uv run ruff check .` + `uv run mypy app` clean (whole repo).
- `uv run alembic upgrade head` from a scratch DB green; every migration downgrade-tested.
- Contract: all spec API-surface paths present; validator green; no individual contributor paths removed (additive).
- Security: privacy schema test (Task 5) proves `authoring_member_id`/member identity absent from public schemas; XOR CHECKs enforce a single seller at the DB; RBAC via dependencies only; no token/PII logging introduced.

## Risks

- **Breadth:** frameworks + projects + financials + organizations + explore + reputation + auth (`user_roles`). Mitigation: additive XOR keeps one seller model; plan slices by module; full suite every task.
- **Derived-vs-self role marker (Task 1):** `sync_derived_roles` must never delete a `source="self"` role — dedicated unit test; the backfill classifies existing rows (attestor→derived, else self).
- **Money-path beneficiary (Task 6, 7):** framework-sale + milestone-release payee resolution touches financials; XOR/CHECK enforce a single beneficiary at the DB; escrow semantics frozen; explicit architect attention on those task reviews.
- **Shared legal identity re-point (Task 7):** moves the attestor invoicing legal-name source to `org_legal_profiles` — backward-compatible; flagged for explicit review on that task.
- **Parallel migration heads:** every migration takes `alembic heads` at implementation time; chain, never fork.
