# Step-up 2FA sessions + admin trust console — design

**Date:** 2026-09-13
**Status:** Approved 2026-09-13 (TTL 600 s; bound to the user; indicator in admin + organization shells)
**Slice:** 1 of 3 in the organizations + attestation rework (2: org onboarding journey, 3: attestation request → report)

## Why

The 2026-09-13 audit of organizations + attestation found the 2FA gate is the single biggest source of friction and inconsistency:

- 31 request schemas carry a `totp_code` body field; ~41 service call sites verify it. Every action prompts for a fresh code, so an admin working a queue re-types codes for each row.
- The rule is uneven. KYB verdicts, dispute resolution, needs-admin assign/refund and credential verify are gated. Attestor application approve/reject, trial pass/fail, capability suspend/reinstate/revoke and platform org suspend are not, although they change the same trust state.
- The frontend has six hand-rolled TOTP inputs beside the shared `TotpInput`. The admin KYB queue shares one code field across every row. The 803-line org-attestor review panel has no TOTP field at all. The KYB review schema rejects backup codes (`max_length=6`).
- BR-AUTH-004 lists three 2FA operations; the code has nine. No registry exists.

The admin console mirrors the fragmentation: attestor applications are reviewable from two pages with different powers, disputes stacks two unrelated queues, and 17 flat nav links have no grouping.

## Locked decisions (human, 2026-09-13)

1. **Step-up session + uniform rule.** One TOTP verification unlocks sensitive actions for a fixed window. One rule decides what is sensitive; it applies to admins and organization owners alike.
2. **Super admin stays as is.** The `is_superadmin` flag keeps exactly its current three powers: grant the admin role, edit platform config, immune to suspension. Every admin may verify orgs, approve attestors, suspend/revoke, resolve disputes.
3. **Slice order.** This slice first; org onboarding journey second; attestation request → report third.

## Design

### 1. Step-up session (backend)

| Item | Decision |
|---|---|
| Endpoint | `POST /v1/auth/step-up` body `{ "code": str }` — verifies TOTP or backup code through the existing `_verify_totp_or_backup_code` + lockout helpers. Returns `{ "verified_until": datetime }`. `GET /v1/auth/step-up` returns `{ "active": bool, "verified_until": datetime \| null }`. |
| Storage | Redis key `stepup:{user_id}` → value `verified_at` ISO string, TTL `STEP_UP_TTL_SECONDS` (settings, default **600**). Not a JWT claim: revocable, no token re-issue, survives access-token rotation. |
| Revocation | `POST /v1/auth/logout` and `disable_totp` delete the key. Admin `suspend_user` deletes the target's key. |
| Dependency | `require_step_up` in `app/core/dependencies.py`. Order: `get_current_user` → `totp_enabled` else 403 `{"error_code": "totp_setup_required", "onboarding_url": "/settings/security"}` → Redis key present else 403 `{"error_code": "step_up_required"}`. No audit on a miss (normal flow). |
| Composition | Applied at the router as an extra `Depends` beside the role/org-role gate. Service functions lose their `totp_code` parameter and internal verify calls. Request schemas lose `totp_code`. |
| Audit | Successful step-up writes audit `step_up_verified`. Gated endpoints keep their existing audit rows. |
| Rate limit | Step-up endpoint reuses the TOTP failure lockout (5 wrong codes / window). |

### 2. Uniform rule — what requires step-up

**Rule:** any request that changes trust state, money state, account identity, or privilege.

Registry (the router is the enforcement; this table is the contract):

| Area | Endpoint | Today | After |
|---|---|---|---|
| Auth/settings | email change, 2FA disable, backup-code regen, GDPR deletion | gated | gated |
| Financials | payout request, payout account change, payment-method add/remove (user + org) | gated | gated |
| Developer | commission payout, application approve/reject | gated | gated |
| Organizations (owner) | transfer ownership, legal profile upsert, sign attestor undertakings | gated | gated |
| Admin: users | role assignment, KYC verdict, suspend/unsuspend | gated | gated |
| Admin: frameworks | suspend/unsuspend, moderation verdicts | gated | gated |
| Admin: config | platform config patch (super admin) | gated | gated |
| Admin: credentials | verify / reject | gated | gated |
| Admin: attestation | dispute resolve, needs-admin assign, needs-admin refund | gated | gated |
| Admin: project disputes | resolve | gated | gated |
| Admin: organizations | KYB verdict | gated | gated |
| Admin: organizations | **org suspend / reinstate** | open | **gated** |
| Admin: organizations | **capability suspend / reinstate / revoke** (×3 capabilities) | open | **gated** |
| Admin: attestors | **application approve / reject** | open | **gated** |
| Admin: attestors | **trial decide (pass/fail)** | open | **gated** |

Explicitly **not** gated (triage, reads, reversible drafts): needs-info, start-trial, calibration fixture CRUD, all list/detail reads, org purchases and project funding (card auth is the control, per 2026-07-10 org-operator design), org self-activation of contributor/operator capability, invitations, team edits.

BR-AUTH-004 is amended by this spec to point at this registry.

### 3. Step-up (frontend)

- `installStepUpInterceptor()` beside the existing 401-refresh and incomplete-user interceptors. On a 403 whose body is `{"error_code": "step_up_required"}` it opens the global `StepUpDialog`, awaits verification, and retries the original request once via direct `fetch` (same single-retry pattern as the 401 interceptor). On `totp_setup_required` it dispatches the existing incomplete-user event with the security settings URL.
- `StepUpDialog`: one modal, uses `TotpInput`, accepts backup codes (`xxxx-xxxx`), shows lockout copy from the API. Concurrent 403s share one in-flight dialog promise.
- `useStepUpStatus()` reads `GET /v1/auth/step-up` and exposes `verifiedUntil`. The admin shell and the organization shell show a small "Verified · 8 min" pill with a lock icon while active; nothing when inactive.
- Every per-form TOTP input is removed: 6 hand-rolled inputs, 8 `TotpInput` usages in admin panels and the org financials tab. Forms submit directly; the interceptor handles the prompt.
- `TotpInput` keeps its id unique per instance (`useId`) since the dialog can coexist with the 2FA setup screen.

### 4. Admin trust console

Routes after this slice:

| Route | Content | Replaces |
|---|---|---|
| `/admin/attestors` | Tabs: **Applications** (queue + detail with gate checklist, documents, needs-info/approve/reject, capability controls), **Trials** (start, grade, decide), **Fixtures** (calibration fixture CRUD) | `/admin/org-attestors`, `/admin/calibration-fixtures`, and the application rows on `/admin/attestations` |
| `/admin/attestations` | Needs-admin queue (assign/refund), browse by status, detail | same page minus application rows |
| `/admin/disputes` | Tabs: **Attestation**, **Project**; badge counts per tab | stacked panels |
| `/admin/organizations` | KYB queue + directory, suspend/reinstate with visible error state | same page, silent-error bug fixed |
| `/admin/credentials` | unchanged | |

Old routes redirect to the new ones. The 803-line review panel splits into `attestor-application-queue`, `attestor-application-detail`, `attestor-trial-grader`, `attestor-capability-controls`, each under 200 lines.

Admin nav groups the 17 links into four sections: **Marketplace** (Analytics, Moderation, Users, Invoices), **Trust** (Attestors, Attestations, Credentials, Organizations, Disputes), **Money** (Money, Payouts), **Platform** (GDPR, Connectors, Waitlist, Developer, Configuration). Badges: needs-admin count on Attestations, submitted count on Attestors, open count on Disputes.

Status rendering: every admin status pill goes through one `StatusPill` map (label + semantic tone) so "submitted", "needs_info", "in_review" read and colour the same on every admin screen. Requestor and attestor screens adopt the same map in slice 3.

Backend routers are **not** moved. The three-router split is churn without user value; the console is the unifying layer.

### 5. Out of scope (later slices)

- Owner notifications on org/capability suspend, reinstate, revoke (slice 2).
- Org list and invitation flow consolidation, KYB waiting states (slice 2).
- Requestor status vocabulary, framework-page entry point, workspace (slice 3).
- Any change to the login-time `totp_verified` claim.

## Security

- Step-up lives in Redis per user, not per device. A stolen access token during the window inherits the step-up. Mitigation: 10-minute TTL, logout revocation, suspend revocation, and access tokens are memory-only. Documented as an accepted trade-off; the architect may shorten the TTL via settings.
- The dependency never bypasses the role gate; both must pass. Denials from the role gate still audit.
- No secret material in logs: the step-up endpoint logs `user_id` and `action` only.

## Data / contract changes

- No migration. Redis only.
- `contracts/openapi.yaml`: add `/v1/auth/step-up` GET + POST; remove `totp_code` from 31 request schemas; add the 403 `StepUpRequired` response component to gated operations. Regenerate the frontend client.

## Tests

Backend (pytest):
- unit: step-up service verify/TTL/lockout/revoke on logout, disable, suspend.
- unit: `require_step_up` returns 403 `totp_setup_required` / `step_up_required` / passes.
- integration: one test per gated endpoint (the registry above, 19 rows) asserting 403 without step-up and 2xx with it; 34 existing test files that post `totp_code` are updated to seed a step-up key via a fixture.

Frontend (vitest):
- interceptor: opens dialog on `step_up_required`, retries once, shares one dialog across concurrent 403s, passes through other 403s.
- `StepUpDialog`, `useStepUpStatus`, status pill map.
- rewritten tests for the split attestor console components and the tabbed disputes page.

End-to-end (Playwright): `admin-trust-console.spec.ts` — step-up prompt appears on first KYB verdict, second verdict in the same window needs no prompt, attestor application approve from the new page, dispute tab switch.

## Open questions for the architect

1. TTL: 600 s default. Accept?
2. Redis per user (recommended) vs per access-token `jti` (dies every 15 min, defeats the point) vs per refresh session (needs a session id on the access token; not present today).
3. Should the step-up pill also appear in the organization shell for owners, or admin shell only?
