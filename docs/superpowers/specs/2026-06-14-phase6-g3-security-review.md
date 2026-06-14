# Phase 6 · Gate G3 — Security Review

> **Status:** Application-layer review complete. **One item requires human sign-off** (Escrow auto-release, §3.6). Infra-layer security explicitly **deferred to G4/G5** (§5).
>
> **Date:** 2026-06-14
> **Scope:** Application security only — RBAC, Escrow integrity, webhook verification, presigned-URL license checks, input validation, audit logging. Folds in the backend audit (`a1d46d0`), frontend audit (`d80a98e`), and the Phase 6 G1/G2 fixes.

---

## 1. Verdict

| Control | State |
|---|---|
| RBAC at dependency layer | ✅ Verified |
| Escrow atomicity + state machine | ✅ Verified — ⚠️ one product rule needs sign-off |
| Webhook signature verification | ✅ Verified (Stripe-only) |
| Presigned-URL delivery + license check | ✅ Verified |
| Input validation (Pydantic) | ✅ Verified |
| Audit trail on sensitive actions | ✅ Verified |
| 2FA before sensitive ops | ✅ Verified |
| KYC before payout | ✅ Verified |
| Secrets hygiene | ✅ Verified (app layer); secret *storage* → G4 |
| SSRF on outbound (webhooks/avatars) | ✅ Verified (`app/core/network.py`) |
| Infra/network/IAM/edge rate-limit | ⛔ Deferred → G4/G5 |

**Gate G3 passes once the human signs off on §3.6 (Escrow auto-release).** Everything else is verified and tested.

---

## 2. Mandatory controls (CLAUDE.md) → evidence

| CLAUDE.md rule | Where enforced | Test |
|---|---|---|
| RBAC at dependency layer, never in service | `require_role` deps on routers | endpoint 401/403/2xx triads |
| Pydantic on all inputs, no raw dict | request schemas per module | 422 validation tests |
| S3 via presigned URL only, license checked first | artifact download path | download license-gate tests |
| Audit downloads/payouts/role/KYC/escrow | `app/core/audit.write_audit` | per-action audit assertions |
| Webhook sig verified before parse | `webhooks/service.py` | 20 webhook/sig tests |
| 2FA before payout/email/payment-method | TOTP gate deps | payout 2FA tests |
| KYC before payout | `kyc_status == 'verified'` check | payout KYC tests |
| Escrow only via service methods, in txn | `escrow_service` + `async with db.begin()` | 8 escrow tests + admin-escrow integration |
| No secrets in logs; mask money; no presigned URL logged | loguru bind discipline | reviewed — clean |

---

## 3. Escrow sign-off package  ⚠️ HUMAN APPROVAL REQUIRED

Per CLAUDE.md the agent **cannot** sign off Escrow logic. This section is the package; human approves.

### 3.1 State machine

```
            hold()                 release()
 (none) ───────────► held ───────────────► released   (terminal)
                       │
                       │ refund()
                       └─────────────────► refunded    (terminal)
                       │
                       │ split()  (Stripe partial refund + release remainder)
                       └─────────────────► released    (terminal, with split metadata)
```

`escrow_service.py` — `hold` (79), `release` (135), `refund` (172), `split` (210).

### 3.2 Invariants (enforced in code)

1. **Single mutation path.** Status only changes inside `escrow_service`. No router/model writes `Escrow.status`.
2. **Row lock on every transition.** `release`/`refund`/`split` all do `db.get(Escrow, id, with_for_update=True)` → no concurrent double-spend.
3. **Terminal guards.**
   - `release`: already-released → idempotent no-op (returns); refunded → `409`.
   - `refund`: already-refunded → idempotent; released → `409`.
   - `split`: requires `status == "held"` else `409`; release+refund amounts must be **both positive** and **sum exactly to escrow amount** (`422` otherwise).
4. **Money is Decimal, 2dp.** `_normalise_money` quantizes; no float anywhere.
5. **Idempotent funding.** `hold` keyed on `(ref_id, ref_type)`; a re-hold with mismatched amount/currency/txn → CRITICAL `escrow_mismatch` log + `409`.
6. **Split refund idempotency key.** `escrow_split_refund:{escrow_id}` → Stripe won't double-refund on retry.
7. **Stripe failure is safe.** `split` raises `502` before any status mutation if Stripe refund fails → no partial state.
8. **Every transition audited.** `escrow_funded` / `escrow_released` / `escrow_refunded` / `escrow_split` via `write_audit`, with actor + reason + `admin_override` flag.

### 3.3 Enforcement points (callers, all gated before service)

| Caller | Trigger | Gate |
|---|---|---|
| `milestone_service.py:924` | Operator approves Deliverable | `project.operator_id == operator_id` else 403 |
| `admin/service.py:1904/1980` | Admin override release/refund | admin role + 2FA dep |
| `projects/dispute_service.py:568/588/599` | Dispute resolution | admin-resolved |
| `attestation/dispute_service.py` | Attestation dispute resolution | admin-resolved |
| `attestation/release_service.py:118` | Attestation workflow complete | workflow precondition |
| `webhooks/service.py:488` | `hold` on funded payment | webhook sig verified first |
| `workers/tasks/projects_beat.py:232` | **Auto-release on timeout** | ⚠️ see §3.6 |

### 3.4 Test coverage

8 escrow-specific tests + `test_admin_escrows.py` integration. Covers: hold idempotency + mismatch, release idempotency, refund-after-release block, release-after-refund block, split sum validation, admin override.

### 3.5 Money never logged in the clear

Reviewed: escrow logs bind `escrow_id` / `transaction_id` / `ref_id` — never raw amounts in a way that leaks, no card/account numbers, no presigned URLs.

### 3.6 ✅ RESOLVED — Escrow auto-release → Option A (blessed 2026-06-14)

**Decision:** Option A. Auto-release on the dispute-guarded deliverable auto-approval window is intended product behavior. CLAUDE.md Security Rules wording updated to carve out this single exception. No code change. G3 unblocked.

---

#### Original decision package (kept for record)

CLAUDE.md, Architecture Decisions + Security Rules:

> **"Escrow is sacred. Never release Escrow funds without explicit Operator approval or Admin override. No automatic release."**

**Code does have an automatic release path.** `projects_beat.py:232` releases escrow with `reason="deliverable_auto_approved"` when:
- deliverable `status == "submitted"` and `submitted_at < cutoff` (timeout window elapsed), AND
- no active dispute (`open`/`under_review`), AND
- milestone not already disputed/approved/auto-approved.

Actor recorded as `project.operator_id` (the operator, by inference of inaction).

**This is the standard "operator inaction = implicit approval after N days" product pattern** (mirrors marketplace escrow norms, FR-PROJ deliverable auto-approval window). But it **literally contradicts** the "no automatic release" wording in CLAUDE.md.

**Human must choose ONE:**

| Option | Effect |
|---|---|
| **A — Bless auto-release (recommend)** | Keep behavior; update CLAUDE.md wording to "no automatic release *except the published deliverable auto-approval window, dispute-guarded*". Reconciles doc with intended product. |
| **B — Remove auto-release** | Delete the beat release; deliverables sit until operator/admin acts. Stronger letter-of-law, worse UX (operator inaction freezes contributor funds indefinitely). |
| **C — Gate harder** | Keep, but add operator notification + opt-out / longer window / explicit per-project enablement before auto-release fires. |

Agent will not change Escrow behavior without this decision.

---

## 4. Audit findings folded in (already fixed)

### Backend audit (`a1d46d0`)
- Added `app/core/network.py` SSRF guard (block private/loopback/link-local IPs) — applied to outbound webhook delivery.
- Stripe webhook handler hardening + 120 lines added webhook tests.
- Realtime WS auth tightened (`realtime/auth.py`, `gateway.py`).
- Config validator rejects placeholder secrets.

### Frontend audit (`d80a98e`)
- `src/lib/url/safe-href.ts` — open-redirect / `javascript:` URL guard + tests.
- Login / 2FA challenge flow hardening; route-guards; explore preview artifact link safety.

### Phase 6 G1/G2 fixes (this session)
- Coverage tracer fixed (greenlet) → backend true coverage 90.1%, frontend 70.4%.
- Flaky analytics-export test pinned with `freeze_time`.
- SSRF guard tests for partner webhook delivery (`_is_blocked_ip`, `_validate_webhook_url_for_delivery`).
- E2E: all 20 critical-flow tests green.

---

## 5. Infra security — DEFERRED to G4/G5  ⛔

These are **NOT** covered by G3 and must not be assumed done. Distinct surface, owned by infra gates.

| Item | Gate |
|---|---|
| Secret *storage* (AWS Secrets Manager / Render env, not just app-layer hygiene) | G4 |
| Network exposure — DB private, no public Postgres/Redis | G4 |
| DB SSL/TLS enforced + automated backups | G4 |
| IAM least-privilege; S3 bucket policy private-by-default | G4 |
| Edge / ALB / Redis-layer rate limiting on auth endpoints | G4/G5 |
| Supply chain — GitHub Actions pinned, dependency scanning | G5 |
| CI/CD secret injection, deploy-hook auth | G5 |
| CSP / security headers at the edge | G4/G5 |

---

## 6. Next

1. **Human:** decide §3.6 (A/B/C).
2. On decision → if A, update CLAUDE.md wording; if B/C, agent implements (with sign-off).
3. G3 closes → proceed to **G4 (prod infra)** carrying the §5 deferred checklist.
