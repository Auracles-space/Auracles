# Organizations as Operators (Sub-project 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `operator` org capability real end-to-end — self-activation → org buys Frameworks into a shared library its teams/members consume → org pays from an org payment method → org posts and funds custom Projects and approves deliverables (releasing Escrow to Contributors) — additively, without retiring individual operators.

**Architecture:** Additive. Demand-side ownable entities (`licenses`, `projects`, `reviews`, `transactions`) become ownable by a user **or** an org via the XOR pattern already shipped on the payee side (`transactions.payee_org_id`). Two genuinely new surfaces: a **shared library** (`license_grants` allocates an org-owned License to teams/individuals; download entitlement = grant lookup) and **pay-in** (`organizations.stripe_customer_id` + `transactions.payer_org_id`, mirroring the audited per-user SetupIntent/PaymentIntent flow). No drop migrations — every migration is additive or relax-only. Spec: `docs/superpowers/specs/2026-07-10-org-operator-design.md` — read it before any task.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, pytest(-asyncio) + httpx AsyncClient, Redis rate limiter, existing Stripe/Paystack purchase + escrow plumbing.

## Global Constraints

- Backend only. No frontend files. Frontend client regen deferred to a separate frontend plan.
- Run pytest from `backend/`: `uv run pytest tests -x -q`. **Never run pytest concurrently** (shared dev DB).
- Before claiming any task clean: `uv run ruff check .` (whole repo) and `uv run mypy app` from `backend/`.
- Every migration: `uv run alembic upgrade head` and `uv run alembic downgrade -1` both green, then `upgrade head` again. Migration `down_revision` = current head at implementation time (`uv run alembic heads`) — never fork the revision chain, rebase it. Head at plan time is `2026_07_08_0072`; earlier tasks land first, so read the live head per task.
- Coverage ≥80% on touched modules.
- OpenAPI: after each endpoint task, regenerate `contracts/openapi.yaml` from `app.openapi()` using the established regen practice, and validate with `openapi_spec_validator`.
- Commit after each task. Commit messages end at the last meaningful line — **no `Co-Authored-By` trailer**. Work on `main`.
- RBAC only via FastAPI dependencies (`require_org_role`, `require_org_capability` from `app/modules/organizations/dependencies.py`; platform-admin dep from the existing admin module). **Never** role checks inside services.
- Spend authority: buy Framework, post/fund Project, approve deliverable (Escrow release), raise/settle dispute, mutate org payment method → `require_org_role("admin")` (owner inherits). Members consume granted Licenses + read only.
- Money paths: all writes inside DB transactions; Escrow semantics untouched — only payer/beneficiary resolution changes. Never log tokens, card details (mask `****1234`), payment-method refs unmasked, or PII.
- Provenance confidentiality: `license_grants.member_id`, `granted_by`, `projects.posting_member_id`, `reviews.reviewing_member_id` (and any member identity) NEVER appear in public / buyer / Contributor response schemas. Leakage is a review blocker.
- Domain language exact: Framework, Artifact, License, Project, Proposal, Milestone, Deliverable, Escrow, Contributor, Operator — never abbreviate.

## Additive-only rules

- No column or table is dropped in this sub-project. `operator_id` on `licenses`/`projects`/`reviews` and `payer_id` on `transactions` are relaxed NOT NULL → nullable and coexist with the new org columns; individual rows keep using the user column.
- Every XOR is a DB `CHECK ((user_col IS NULL) != (org_col IS NULL))`; individual paths keep writing the user column, org paths write the org column.
- The `operator` capability has **no profile table and no reputation** (operators are not publicly rated). Activation writes only the `org_capabilities` row + syncs the derived role.

---

### Task 1: Operator capability activation + operator derived role

**Files:**
- Create: `backend/app/modules/organizations/operator_service.py`, `backend/tests/unit/modules/test_org_operator_capability.py`, `backend/tests/integration/test_org_operator_capability_endpoints.py`
- Modify: `backend/app/modules/organizations/service.py` (`_DERIVED_ROLE_MAP`), `backend/app/modules/organizations/router.py`, `backend/app/modules/organizations/schemas.py`

**Interfaces:**
- Add `"operator": "operator"` to `_DERIVED_ROLE_MAP` in `service.py` (currently `{"attestor": "attestor", "contributor": "contributor"}`). `sync_derived_roles` is already generic over the map — no other change; the `operator` role already exists in `ROLE_ENUM` (`app/modules/auth/models.py`) and is self-selectable, so a user may hold `operator` both `source="self"` and `source="derived"` (uniqueness `(user_id, role, source)` shipped in sub-project 3). Sync only ever touches the `derived` row.
- Produces (in `operator_service.py`, mirroring `contributor_service.py` exactly; commit internally, audit each; `module="organizations"`):
  - `activate_operator_capability(db, *, org_id, actor_id) -> OrgCapability` — org not suspended/deactivated (else 403); upserts `org_capabilities(operator) = active` + `activated_at`; calls `sync_derived_roles` for **every current org member**. **No profile row created** (operator has none). Idempotent (already-active → returns row, no side effects). Audits `org_operator_activated`.
  - `admin_set_operator_capability_status(db, *, org_id, admin_id, status_value: Literal["suspended","active","revoked"])` — platform-admin; sets `org_capabilities(operator).status`; every status change fires `sync_derived_roles` for all members; audits `org_operator_capability_status_changed`.
  - `operator_capability_active(db, *, org_id) -> bool` — True iff the `operator` capability row is `active`. Reused by every later purchase/post/fund/approve gate.
- Endpoints: `POST /v1/orgs/{org_id}/operator-capability/activate` (`require_org_role("admin")`, rate-limited `RateLimiter(namespace="org_operator_activate", limit=5, window=3600)` per org); `POST /v1/admin/orgs/{org_id}/operator-capability/{suspend|reinstate|revoke}` (platform-admin dep). Schemas mirror the contributor-capability response schema.

- [ ] **Step 1: Failing unit tests** — activate sets capability active + grants `source="derived"` `operator` role to a plain member; activate on a suspended org raises 403 (service precondition path); idempotent re-activate has no extra side effects and no profile is created (assert no operator profile table exists / is written); admin suspend revokes the derived role when it is the member's only operator org; reinstate re-grants; a user with a pre-existing `source="self"` operator role keeps it after suspend (sync touches only the derived row); contributor + attestor derived roles unaffected (regression).
- [ ] **Step 2: RED** — `uv run pytest tests/unit/modules/test_org_operator_capability.py -x -q` fails.
- [ ] **Step 3: Implement** `_DERIVED_ROLE_MAP` change + `operator_service.py` + endpoints + schemas.
- [ ] **Step 4: Failing integration tests → implement router:** activate happy + 401 + 403 (plain member) + 403 suspended org; admin suspend/reinstate/revoke happy + 401 + 403 non-admin.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add operator capability self-activation and admin suspension`

### Task 2: License XOR ownership + license_grants table + holder resolution

**Files:**
- Modify: `backend/app/modules/frameworks/models.py` (`License`: add `licensee_org_id`, relax `operator_id`; new `LicenseGrant` model)
- Create: `backend/migrations/versions/2026_07_10_00XX_license_org_ownership.py`, `backend/app/modules/frameworks/license_ownership.py` (holder resolution), `backend/tests/unit/modules/test_license_ownership.py`

**Interfaces:**
- New nullable column on `licenses`: `licensee_org_id UUID FK organizations`; `operator_id` relaxed to nullable; CHECK `ck_licenses_holder_xor ((operator_id IS NULL) != (licensee_org_id IS NULL))`; the existing `UniqueConstraint("framework_id","operator_id", name="uq_licenses_owner")` stays (individuals); add partial `UniqueConstraint`-equivalent via `op.create_index(..., unique=True, postgresql_where=text("licensee_org_id IS NOT NULL"))` on `(framework_id, licensee_org_id)` named `uq_licenses_org_owner`. Index `idx_licenses_org (licensee_org_id)`.
- New model `LicenseGrant` (`__tablename__ = "license_grants"`, `CreatedAtMixin`), columns per spec:
  - `id` PK gen_random_uuid; `license_id UUID FK licenses ON DELETE CASCADE`; `team_id UUID FK org_teams ON DELETE CASCADE NULL`; `member_id UUID FK org_members ON DELETE CASCADE NULL`; `granted_by UUID FK org_members ON DELETE SET NULL NULL`.
  - CHECK `ck_license_grants_target_xor ((team_id IS NULL) != (member_id IS NULL))`.
  - Partial-unique indexes: `uq_license_grants_team (license_id, team_id) WHERE team_id IS NOT NULL`; `uq_license_grants_member (license_id, member_id) WHERE member_id IS NOT NULL`. Indexes on `(member_id)`, `(team_id)`.
- Produces `license_ownership.resolve_license_holder(license) -> LicenseHolder` — dataclass `LicenseHolder(kind: Literal["user","org"], user_id: UUID | None, org_id: UUID | None)`, reads whichever of `operator_id`/`licensee_org_id` is set. Consumed by library, purchase, review, financials read paths.

- [ ] **Step 1: Failing tests** — holder XOR CHECK rejects both-set and neither-set; grant target XOR CHECK rejects both-set and neither-set; `resolve_license_holder` returns `kind="org"` when `licensee_org_id` set else `kind="user"`; partial-unique blocks a second team-grant for the same (license, team) but allows the same team on a different license.
- [ ] **Step 2: RED.**
- [ ] **Step 3: Models + migration + helper.** Relax `operator_id` NOT NULL via `op.alter_column(..., nullable=True)`; downgrade restores NOT NULL (dev DB straight restore, documented) and drops `license_grants` + org columns/indexes. Migration docstring states WHY + spec reference.
- [ ] **Step 4: Migration round-trip green (up / down / up).**
- [ ] **Step 5: GREEN + full gates.**
- [ ] **Step 6: Commit** — `Add license org ownership columns and grant allocation table`

### Task 3: Shared library — grant allocation, entitlement, org artifact download

**Files:**
- Create: `backend/app/modules/organizations/library_service.py`, `backend/tests/unit/modules/test_org_library_entitlement.py`, `backend/tests/integration/test_org_library_endpoints.py`
- Modify: `backend/app/modules/organizations/router.py`, `backend/app/modules/organizations/schemas.py`

**Interfaces:**
- Produces `member_has_license_access(db, *, license_id, member_id) -> bool` — True iff a `LicenseGrant` exists with `member_id == member` OR `team_id` in the teams the member belongs to (`org_team_members`). Pure read; the security-critical entitlement check.
- Grant management (all `require_org_role("admin")`; validate `license.licensee_org_id == org_id`, and the target team/member belongs to the org, else 422; duplicate → 409; audit `license_grant_added` / `license_grant_revoked`, `module="organizations"`):
  - `add_license_grant(db, *, org_id, license_id, actor_member_id, team_id=None, member_id=None) -> LicenseGrant` — exactly one of team/member (else 422); stamps `granted_by = actor_member_id`.
  - `revoke_license_grant(db, *, org_id, license_id, grant_id) -> None`.
  - `list_license_grants(db, *, org_id, license_id) -> list[LicenseGrantResponse]`.
- `list_org_library(db, *, org_id, member) -> list[LibraryItem]` — active org Licenses the caller member is entitled to (direct or via team); reuse the `_library_item` shape from `app/modules/library/service.py`. Admin/owner see the full org License list (management view) with a grant summary; plain members see only entitled Licenses.
- `request_org_artifact_download(db, *, org_id, license_id, artifact_id, member, ip_address) -> ArtifactDownloadResponse` — load the org License (`licensee_org_id == org_id`, active) else 403; enforce `member_has_license_access` else 403; reuse `_artifact_is_covered_by_license_version`, `s3.storage.presigned_get`, and write `ArtifactDownload(license_id, artifact_id, user_id=<caller user_id>, ip_address)` (per-member audit) + `write_audit` `artifact_downloaded`.
- Endpoints:
  - `POST /v1/orgs/{org_id}/licenses/{license_id}/grants` (admin) body `{team_id?}|{member_id?}`
  - `DELETE /v1/orgs/{org_id}/licenses/{license_id}/grants/{grant_id}` (admin)
  - `GET /v1/orgs/{org_id}/licenses/{license_id}/grants` (admin)
  - `GET /v1/orgs/{org_id}/library` (member; entitled Licenses)
  - `POST /v1/orgs/{org_id}/library/{license_id}/artifacts/{artifact_id}/download` (member; entitlement-gated)
- **Provenance:** `LibraryItem` and grant responses must not leak `granted_by` to non-admin members; grant responses (admin-only) may include member/team ids. Download responses expose only the presigned URL + artifact metadata.

- [ ] **Step 1: Failing unit tests** — direct member grant → access True; member in a granted team → access True; member with neither → access False; member removed from a granted team loses access; revoking a grant removes access; grant to a team/member outside the org → 422; duplicate grant → 409; org download without a grant → 403; download of an artifact outside the licensed version snapshot → 403.
- [ ] **Step 2: RED.** **Step 3: Implement service.** **Step 4: Failing integration tests → implement router:** each endpoint happy + 401 + 403 (non-admin on grant mgmt; ungranted member on download) + cross-org 404; assert the per-member `ArtifactDownload` row is written with the consuming user's id.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add org shared library allocation and entitlement-gated downloads`

### Task 4: Org billing — org Stripe customer + payer XOR + org payment methods

**Files:**
- Modify: `backend/app/modules/organizations/models.py` (`Organization.stripe_customer_id`), `backend/app/modules/financials/models.py` (`Transaction.payer_id` relax + `payer_org_id`)
- Create: `backend/migrations/versions/2026_07_10_00XX_org_billing_payin.py`, `backend/app/modules/organizations/billing_service.py`, `backend/tests/unit/modules/test_org_billing.py`, `backend/tests/integration/test_org_payment_methods.py`
- Modify: `backend/app/modules/organizations/router.py`, `backend/app/modules/organizations/schemas.py`

**Interfaces:**
- Migration: `organizations` add `stripe_customer_id TEXT NULL`; `transactions` add `payer_org_id UUID FK organizations NULL`, relax `payer_id` to nullable, CHECK `ck_transactions_payer_xor ((payer_id IS NULL) != (payer_org_id IS NULL))`, index `idx_transactions_payer_org (payer_org_id)`. Downgrade: drop CHECK/column/index, re-assert `payer_id` NOT NULL (documented dev-DB restore), drop `stripe_customer_id`.
- Produces (mirror `financials/service.py` `create_payment_method_setup` / `list_payment_methods` / `delete_payment_method`, but keyed on `organizations.stripe_customer_id` created lazily with idempotency key `stripe_customer:org:{org_id}`; provider routing on org `country` via `select_provider`):
  - `create_org_payment_method_setup(db, redis, *, org_id, actor: User, totp_code) -> PaymentMethodSetupResponse` — TOTP-gated on the requesting admin's own TOTP (reuse `_verify_sensitive_payment_method_change` against `actor`); creates the org Stripe customer if absent; returns a SetupIntent client secret. Audit `org_payment_method_added` (`module="financials"`, `target_type="organization"`).
  - `list_org_payment_methods(db, *, org_id) -> PaymentMethodsResponse` — last4 only, never full PAN.
  - `delete_org_payment_method(db, redis, *, org_id, actor: User, payment_method_id, totp_code) -> PaymentMethodDeleteResponse` — TOTP-gated; ownership-checks the method against the org customer; audit `org_payment_method_removed` with `_masked_provider_ref`.
- Endpoints (all `require_org_role("admin")`, rate-limited `RateLimiter(namespace="org_payment_method_setup", limit=10, window=3600)` on setup): `POST /v1/orgs/{org_id}/financials/payment-methods/setup`; `GET /v1/orgs/{org_id}/financials/payment-methods`; `DELETE /v1/orgs/{org_id}/financials/payment-methods/{payment_method_id}`. Place beside the existing org financials routes (locate with `grep -rn "orgs/{org_id}/financials" backend/app/modules/organizations`).

- [ ] **Step 1: Failing unit tests** — payer XOR CHECK rejects both-set/neither; org customer created lazily once (idempotency key asserted, second call reuses `stripe_customer_id`); setup without TOTP → 401; list returns masked last4 only; delete rejects a method not owned by the org customer → 404.
- [ ] **Step 2: RED.** **Step 3: Models + migration + service.** **Step 4: Migration round-trip green.** **Step 5: Failing integration tests → implement router:** setup happy + 401 + 403 (member) + TOTP-missing 401; list happy + 403; delete happy + 403 + 404.
- [ ] **Step 6: GREEN + full gates + contract regen. Commit** — `Add org payment methods and transaction payer org ownership`

### Task 5: Org Framework purchase + webhook org-license grant

**Files:**
- Modify: `backend/app/modules/financials/service.py` (org purchase initiator), `backend/app/modules/financials/router.py` (org purchase route) OR add org purchase route to `organizations/router.py` (place with other `/orgs/{org_id}/frameworks` org routes if present, else financials — pick per existing org route conventions), `backend/app/modules/webhooks/service.py` (`_handle_purchase_succeeded` org branch)
- Create: `backend/tests/unit/modules/test_org_framework_purchase.py`, `backend/tests/integration/test_org_purchase_flow.py`

**Interfaces:**
- Produces `create_org_framework_purchase(db, *, org_id, actor: User, framework_id, payload: PurchaseRequest) -> PurchaseResponse` — mirrors `create_framework_purchase` but: requires `operator_capability_active(org_id)` (else 403 `capability_suspended`); resolves the org Stripe customer from `organizations.stripe_customer_id` (402 + explicit message if no payment method on file); **self-deal guard** — `resolve_framework_seller(framework).org_id == org_id` → 422 `self_deal_conflict` **before any charge**; existing-org-license guard `UNIQUE(framework_id, licensee_org_id)` → 409; creates the pending `Transaction` with `payer_id=NULL, payer_org_id=org_id` (extend `_create_pending_purchase_transaction` with an org-payer path or add an org sibling); PaymentIntent metadata gains `"payer_org_id": str(org_id)` alongside `transaction_id/kind/framework_id/license_type`.
- `_handle_purchase_succeeded` org branch: when `transaction.payer_org_id is not None`, look up the existing License by `(framework_id, licensee_org_id)`; create `License(licensee_org_id=transaction.payer_org_id, operator_id=None, transaction_id, license_type, status="active", version_at_grant, seats_used=1, seats_total=_license_seats_total(license_type))`; the completion `write_audit` uses `actor_id=None` (org context) with `target_type="transaction"` and `payer_org_id` in metadata (the initiating admin is already audited at `purchase_initiated`). Individual branch (`payer_id`) unchanged.
- Endpoint: `POST /v1/orgs/{org_id}/frameworks/{framework_id}/purchase` (`require_org_role("admin")` + `require_org_capability("operator")`, rate-limited `RateLimiter(namespace="org_framework_purchase", limit=30, window=3600)` per org).

- [ ] **Step 1: Failing unit tests** — org purchase creates a pending transaction with `payer_org_id` set and `payer_id` NULL; buy-own-org-Framework → 422 `self_deal_conflict` (no transaction, no Stripe call); purchase with no org payment method → 402; purchase while capability suspended → 403; second org license on the same framework → 409; webhook org branch creates a `licensee_org_id` License (operator_id NULL) and completes the transaction; individual purchase + webhook path unchanged (regression).
- [ ] **Step 2: RED.** **Step 3: Implement initiator + webhook branch.** **Step 4: Failing integration tests → implement route:** org purchase happy (mock provider) + 401 + 403 (member) + 403 suspended + 402 no-method + 422 self-deal; then drive the webhook to assert the org License is granted and appears in `GET /v1/orgs/{org_id}/library` for a granted member after a grant.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add org framework purchase and webhook org license grant`

### Task 6: Projects operator XOR + org project posting + self-deal bid guard

**Files:**
- Modify: `backend/app/modules/projects/models.py` (`Project`: add `operator_org_id`, `posting_member_id`, relax `operator_id`), `backend/app/modules/projects/service.py` (org post + operator resolution + extend proposal self-deal), `backend/app/modules/projects/router.py`, `backend/app/modules/projects/schemas.py`
- Create: `backend/migrations/versions/2026_07_10_00XX_project_operator_org.py`, `backend/app/modules/projects/operator_ownership.py` (operator resolution), `backend/tests/unit/modules/test_project_operator_ownership.py`, `backend/tests/integration/test_org_project_posting.py`

**Interfaces:**
- Migration: `projects` add `operator_org_id UUID FK organizations NULL`, `posting_member_id UUID FK org_members ON DELETE SET NULL NULL`, relax `operator_id` nullable, CHECK `ck_projects_operator_xor ((operator_id IS NULL) != (operator_org_id IS NULL))`, index `idx_projects_operator_org_status (operator_org_id, status)`. Downgrade drops them + re-asserts NOT NULL (documented).
- Produces `operator_ownership.resolve_project_operator(project) -> ProjectOperator` — dataclass `ProjectOperator(kind: Literal["user","org"], user_id: UUID | None, org_id: UUID | None)`. Consumed wherever project code reads "who operates this project" (workspace access, listing, funding, approval).
- `create_org_project(db, *, org_id, actor: User, posting_member_id, payload) -> ProjectResponse` — requires `operator_capability_active(org_id)`; stamps `operator_org_id=org_id`, `operator_id=NULL`, `posting_member_id`. Same validation as individual `create_project`. **Do NOT fork** the individual create — thread an operator descriptor (`ProjectOperator`) through, matching how sub-project 3 threaded `FrameworkOwner`.
- Extend the proposal self-deal guard in `service.py`: the existing individual guard rejects a Contributor whose id equals the project operator; add **org-level** — reject a proposal whose `contributor_org_id == project.operator_org_id` → 422 `self_deal_conflict` (an org's Contributor arm cannot bid on its own operator Project). The existing member-level COI (Contributor is a member of the operating org) still applies.
- **Query-shape sweep:** every `Project.operator_id ==`/`select(Project.operator_id)` site (there are many in `service.py`) must go through `resolve_project_operator` or tolerate `operator_id IS NULL`. Grep `grep -rn "operator_id" backend/app/modules/projects` and audit each: workspace access, listing filters, notifications recipient resolution.
- Endpoints (all `require_org_role("admin")` + `require_org_capability("operator")`, `posting_member_id` = caller's OrgMember): `POST /v1/orgs/{org_id}/projects`; `GET /v1/orgs/{org_id}/projects` (org's projects, owner/admin). Individual `/v1/projects` routes untouched.

- [ ] **Step 1: Failing unit tests** — operator XOR CHECK rejects both-set/neither; `resolve_project_operator` org vs user; org create stamps org+posting_member, NULL operator_id; org bid where `contributor_org_id == operator_org_id` → 422; individual project create + individual COI unchanged (regression); a listing/workspace path resolves an org-operated project without raising on NULL `operator_id`.
- [ ] **Step 2: RED.** **Step 3: Models + migration + helper + service.** **Step 4: Migration round-trip green.** **Step 5: Failing integration tests → implement router:** org post happy + 401 + 403 (member) + 403 capability inactive; org project list happy + 403; self-deal bid 422.
- [ ] **Step 6: GREEN + full gates + contract regen. Commit** — `Add project operator org ownership and org project posting`

### Task 7: Org project money path — accept, fund, approve, dispute (admin)

**Files:**
- Modify: `backend/app/modules/projects/service.py` (accept), `backend/app/modules/projects/milestone_service.py` (fund + approve/Escrow release resolve payer/beneficiary), `backend/app/modules/projects/dispute_service.py` (raise/resolve), `backend/app/modules/projects/router.py`, `backend/app/modules/projects/notifications.py` (auto-approval recipient)
- Create: `backend/tests/unit/modules/test_org_project_money_path.py`, `backend/tests/integration/test_org_project_lifecycle.py`

**Interfaces:**
- Milestone funding: when the project operator resolves to an org (`resolve_project_operator(project).kind == "org"`), the funding `Transaction` is stamped `payer_org_id=org_id, payer_id=NULL` and the charge draws the org Stripe customer (reuse the pay-in path from Task 4/5). Escrow amount/logic untouched.
- Deliverable approval → `escrow_service.release`: **beneficiary resolution unchanged** (already routes to `payee_org_id` when the Contributor is an org, per sub-project 3). Only the funding/refund payer side newly resolves to the org. Do not modify `escrow_service.release` beneficiary logic.
- Auto-approval window: for an org-operated project, "the operator" for the inaction timer + notifications is the org's owner/admins — resolve recipients via org membership (owner/admins) instead of a single `operator_id` user. This remains the only automatic Escrow release.
- Dispute: raise/participate/resolve routed to org admins; refund resolution routes the refund to `payer_org_id`. Reuse existing dispute resolution; only payer resolution changes.
- Endpoints (all `require_org_role("admin")` + `require_org_capability("operator")`, guarding `project.operator_org_id == org_id`): `POST /v1/orgs/{org_id}/projects/{project_id}/proposals/{proposal_id}/accept`; `POST /v1/orgs/{org_id}/projects/{project_id}/milestones/{milestone_id}/fund`; `POST /v1/orgs/{org_id}/projects/{project_id}/deliverables/{deliverable_id}/approve`; `POST /v1/orgs/{org_id}/projects/{project_id}/disputes`.

- [ ] **Step 1: Failing unit tests** — org milestone funding stamps `payer_org_id` + charges the org customer; approval releases Escrow to the Contributor beneficiary (individual and org Contributor); auto-approval on operator inaction fires for an org project and notifies org admins; dispute refund routes to `payer_org_id`; a member (non-admin) cannot fund/approve/dispute → 403 (dependency); funding while capability suspended → 403.
- [ ] **Step 2: RED.** **Step 3: Implement.** **Step 4: Failing integration tests → implement router:** each money endpoint happy (mock provider) + 401 + 403 (member) + cross-org 404; full org project lifecycle — accept → fund → approve → Escrow released to Contributor.
- [ ] **Step 5: GREEN + full gates + contract regen.**
- [ ] **Step 6: Commit** — `Add org project accept, funding, approval, and dispute money path`

### Task 8: Org reviews — reviewer XOR + org review write

**Files:**
- Modify: `backend/app/modules/frameworks/models.py` (`Review`: add `reviewer_org_id`, `reviewing_member_id`, relax `operator_id`), `backend/app/modules/frameworks/service.py` (org review create), `backend/app/modules/frameworks/schemas.py`, `backend/app/modules/organizations/router.py` (or frameworks router — place per existing org route conventions)
- Create: `backend/migrations/versions/2026_07_10_00XX_review_reviewer_org.py`, `backend/tests/unit/modules/test_org_framework_review.py`, `backend/tests/integration/test_org_review_endpoints.py`

**Interfaces:**
- Migration: `reviews` add `reviewer_org_id UUID FK organizations NULL`, `reviewing_member_id UUID FK org_members ON DELETE SET NULL NULL`, relax `operator_id` nullable, CHECK `ck_reviews_reviewer_xor ((operator_id IS NULL) != (reviewer_org_id IS NULL))`, partial-unique `uq_reviews_framework_reviewer_org (framework_id, reviewer_org_id) WHERE reviewer_org_id IS NOT NULL` (existing `uq_reviews_framework_operator` stays for individuals). Downgrade drops them + re-asserts NOT NULL (documented).
- Produces `create_org_framework_review(db, *, org_id, actor: User, reviewing_member_id, framework_id, payload) -> FrameworkReviewResponse` — requires an active org License (`licensee_org_id == org_id`) for the framework (else 403); stamps `reviewer_org_id=org_id`, `operator_id=NULL`, `reviewing_member_id`; one review per framework per org (409 on duplicate); feeds Contributor reputation identically to individual reviews. `_review_to_response` must resolve reviewer identity to the org and **omit `reviewing_member_id`** from the public response.
- Endpoint: `POST /v1/orgs/{org_id}/frameworks/{framework_id}/review` (`require_org_role("admin")` + `require_org_capability("operator")`).

- [ ] **Step 1: Failing unit tests** — reviewer XOR CHECK rejects both-set/neither; org review requires an active org License → 403 without one; org review stamps `reviewer_org_id` + `reviewing_member_id`, NULL `operator_id`; duplicate org review → 409; public review response omits `reviewing_member_id` (schema-level leak-guard); individual review path unchanged (regression).
- [ ] **Step 2: RED.** **Step 3: Models + migration + service.** **Step 4: Migration round-trip green.** **Step 5: Failing integration tests → implement route:** org review happy + 401 + 403 (member, or no license) + 409 duplicate.
- [ ] **Step 6: GREEN + full gates + contract regen. Commit** — `Add org framework reviews under org identity`

### Task 9: GDPR touchpoints, provenance leak-guard, and full lifecycle test

**Files:**
- Modify: `backend/app/modules/gdpr/export_service.py`, `backend/app/modules/gdpr/deletion_service.py`
- Create: `backend/tests/integration/test_org_operator_lifecycle.py`, `backend/tests/unit/modules/test_org_operator_provenance_privacy.py`; extend `backend/tests/integration/test_gdpr_exports.py`, `backend/tests/integration/test_gdpr_account_deletion.py`

**Interfaces:**
- GDPR export (`build_data_export_bundle`): add `_collect_org_operator_activity(db, user_id)` → dict with `library_downloads` (this user's `ArtifactDownload` rows against org Licenses — artifact_id + downloaded_at, no org billing), `project_postings` (Projects where `posting_member_id` is this user's OrgMember — project_id + created_at), `review_authorship` (Reviews where `reviewing_member_id` is this user's OrgMember — framework_id + created_at). Ids + dates only; **org billing / payment methods / org transactions excluded** (org financials, not personal). Wire under key `"organization_operator_activity"`.
- GDPR deletion (`collect_blocked_reasons`): the member's own individual operator obligations already apply; org obligations (org-owned Licenses, org-funded in-flight milestones) belong to the org, not the member — a member leaving does not block on them, and their `license_grants` / `org_team_members` cascade-delete (Task 2). Add a test asserting a member with only org-operator activity (grants, postings) is **not** blocked, and their grants are gone after deletion.
- Provenance privacy: one schema-level test module asserting `granted_by`, `license_grants.member_id`, `posting_member_id`, `reviewing_member_id` never appear in any public / buyer / Contributor response schema (library item, review response, project public view). Extend the existing leak-guard convention used for `authoring_member_id` / `reviewing_member`.
- Full lifecycle integration test (single flow, real routes, mock provider): activate operator capability → add org payment method → purchase a Framework → grant to a team + to an individual → granted member downloads (per-member audit row) → ungranted member 403 → revoke → 403 → post an org Project → accept a Contributor proposal → fund a milestone (org card, `payer_org_id`) → approve deliverable → Escrow released to the Contributor. Assert the individual operator path still works unchanged (regression) somewhere in the suite.

- [ ] **Step 1: Failing tests** — export bundle includes `organization_operator_activity` (ids+dates) and excludes org billing/transactions; deletion not blocked by org-operator activity and grants removed after; provenance leak-guard schema test; the full lifecycle test above.
- [ ] **Step 2: RED.** **Step 3: Implement GDPR touchpoints + any privacy fixes surfaced.** **Step 4: GREEN.**
- [ ] **Step 5: Full gates + final contract regen + `openapi_spec_validator`.**
- [ ] **Step 6: Commit** — `Add org operator GDPR touchpoints and end-to-end lifecycle test`

## Verification (whole plan)

- Every task: `uv run pytest tests -x -q` green (never concurrent); `uv run ruff check .`; `uv run mypy app`; coverage ≥80% on touched modules.
- Every migration task: `alembic upgrade head` + `downgrade -1` + `upgrade head` all green; revision chain rebased on the live head, never forked.
- Contract regenerated + validated after every endpoint task; frontend client regen deferred to the separate frontend plan.
- Money paths: all writes in DB transactions; Escrow release beneficiary logic untouched; only payer/refund resolution newly resolves to the org.
- Individual operator path (purchase, library download, project post/fund/approve, review) unchanged — regression-tested.

## Risks

- **Breadth:** touches licensing + library + projects + financials + organizations + webhooks + auth (`user_roles`) + GDPR. Mitigation: additive XOR (one payer + one licensee model), plan sliced by module, full-suite gate every task.
- **Pay-in is a new surface:** org Stripe customer + `payer_org_id` charging is the first money-in path at org level. Mitigation: mirror the audited per-user SetupIntent/PaymentIntent flow exactly; all charges in DB transactions; explicit review on Tasks 4/5/7.
- **Shared-library access-control correctness:** the grant/team entitlement check (`member_has_license_access`) is the security-critical point — a missed check leaks paid Artifacts to un-granted members. Mitigation: entitlement enforced before every presigned URL + dedicated tests including member-in-multiple-teams, team-removal, and revoke paths (Task 3).
- **`projects.operator_id` query-shape sweep:** relaxing `operator_id` to nullable touches many read sites in `projects/service.py`. Mitigation: explicit grep-and-audit step in Task 6; regression tests on individual workspace/listing/notifications.
- **Webhook org branch:** org purchase completion audits with `actor_id=None`; ensure the individual `payer_id` branch is untouched and the org branch is idempotent. Mitigation: dedicated webhook unit tests both branches (Task 5).
- **Self-deal loops:** org holding both contributor and operator capabilities. Mitigation: buy-own (Task 5) + bid-own (Task 6) both blocked before any charge, covered by dedicated tests.
