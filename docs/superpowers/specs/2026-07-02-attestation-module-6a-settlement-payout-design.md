# Attestation Module 6a — Settlement & Payout — Design

**Date:** 2026-07-02
**Build priority:** 6 (Settlement & Payout), sub-module **a** of 4.
**Status:** Approved for planning.

## 0. Module 6 decomposition

Module 6 (Settlement & Payout, workflow §6.1–6.5) is split into four independent
sub-modules, each its own spec → plan → implement cycle, built in this order:

| Sub-module | Scope | Workflow |
| ---------- | ----- | -------- |
| **6a Settlement** (this doc) | Escrow settles attestation at 90/10; attestor earnings clear immediately and flow to the existing payout balance/withdrawal. | §6.1, §6.2 |
| 6b Reputation | Attestor as a reputation subject; rating (captured in M5) → score; Certified Attestor L5; feed AMM matching. | §6.4 |
| 6c Badge & Provenance | Version-locked attestation badge publish on framework page + attestor public "Completed Attestations" + provenance record, gated on `report_published_eligible`. | §6.3 |
| 6d Invoicing | Attestation tax invoice (requestor) + earnings statement (attestor) + annual summaries. | §6.5 |

## 1. Overview

6a closes the **money** side of the attestation loop. When an attestation settles
(requestor acceptance, 5-business-day auto-acceptance, or dispute rejection — all
already wired in Module 5), the attestor earns **90%** of the fee and the platform
retains **10%**. Earnings become withdrawable immediately and are drawn through the
existing contributor payout infrastructure.

**Deliberately minimal.** The escrow release path is unchanged — 6a introduces no new
escrow math, no new money movement, and no new tables. The "90/10 split" is a
**commission applied at the payout-balance layer**: the platform's 10% is implicit
(never becomes withdrawable), exactly as the framework marketplace already treats its
15% commission. The escrow itself still releases 100% and closes the request.

## 2. Scope boundary

**In scope:**
- Attestation earnings settle at a **10% commission** (vs the marketplace's flat 15%).
- Released attestation earnings clear **immediately** (exempt from the marketplace
  refund-window clearance delay).
- Attestor withdrawal via the existing `Payout` flow.

**Out of scope (other sub-modules / already done):**
- Escrow release triggers and `report_published_eligible` stamping — done in Module 5.
- Badge publication (6c), reputation scoring (6b), invoicing (6d).
- Rating capture — done in Module 5.
- Any change to framework/project payout behavior.

## 3. What already exists (reused unchanged)

- **Escrow release:** `attestation/release_service._release_and_close` calls
  `financials.escrow_service.release` on accept / auto-accept / dispute-rejected,
  sets `status="closed"`, stamps `report_published_eligible = True`.
- **Attestor earnings feed:** `financials.service._sum_transactions` already includes
  `attestation_fee` transactions (`ref_type="attestation"`, `payee_id = attestor`)
  once their escrow is `released`.
- **Withdrawal:** `Payout` + `PayoutAccount` models and the payout-request flow —
  KYC-gated, 2FA-gated, `$50.00` USD minimum via `_minimum_payout`. Attestors are
  users; they reuse this path with no change.
- **Per-transaction columns** `platform_commission` / `net_amount` exist on
  `Transaction` but are vestigial today (purchase transactions stamp
  `platform_commission=0`); commission is applied at the balance layer via a flat
  config rate. 6a keeps that pattern — it does **not** switch to per-row net.

## 4. Money model (locked decisions)

### 4.1 Commission — per-type rate

- New `platform_config` key **`attestation_commission_rate`**, in-code default
  `Decimal("0.10")`. This mirrors `_commission_rate` (default `Decimal("0.15")`),
  which reads config with a code default and requires **no seed migration**. The rate
  is config-overridable at runtime.
- The platform's 10% is **implicit**: it is simply never added to the attestor's
  withdrawable balance. No treasury account, no separate money movement. Identical
  accounting model to the framework marketplace's 15%.

### 4.2 Clearance — immediate on release

- `attestation_fee` earnings are **exempt** from the marketplace `refund_window_hours`
  clearance delay. Rationale: attestation has already passed its 5-business-day
  dispute window before escrow release, so the funds are final at release time.
- Framework/project earnings clearance is **unchanged** (still waits for `cutoff`).

## 5. Balance derivation refactor (the one real code change)

`financials.service._available_payout_balance` today sums **all** earning transactions
together and applies one flat commission rate with one clearance cutoff. Split the
computation into two earning classes, apply each class's own rate and clearance rule,
then combine.

**Marketplace class** — transaction types `purchase`, `milestone` (with released escrow
for milestone), `ref_type` in `{framework, project_milestone}`:
- commission rate = `commission_rate` (0.15 default)
- clears after `cutoff` (`now - refund_window_hours`) — **unchanged**

**Attestation class** — transaction type `attestation_fee`, `ref_type = attestation`,
released escrow:
- commission rate = `attestation_commission_rate` (0.10 default)
- clears **immediately** (no cutoff)

**Combination (per currency):**
```
marketplace_cleared_net = marketplace_cleared_gross * (1 - commission_rate)
attestation_cleared_net = attestation_released_gross * (1 - attestation_commission_rate)
available   = max(marketplace_cleared_net + attestation_cleared_net - claimed, 0)
pending     = marketplace_pending_gross            # attestation is never pending
gross       = marketplace_gross + attestation_gross
```

**Implementation shape:** parameterize `_sum_transactions` so the earning-class filter
(the `or_(...)` type/ref block) is supplied by the caller, then call it once per class.
The marketplace call keeps the exact filter and cutoff it uses today, so the
framework/project payout path stays behaviorally identical.

`_claimed_payouts` is unchanged — `Payout` rows are per-user and currency-scoped
regardless of earning source; a single claimed total is deducted from combined net.

## 6. Earnings response presentation

`EarningsResponse` = `{gross_revenue, pending_clearance, available_balance,
commission_rate}`. A single `commission_rate` cannot represent two rates, so set it to
the **effective blended rate**:

```
commission_rate = 1 - (total_cleared_net / total_cleared_gross)   # 0 when gross == 0
```

This keeps the field honest and meaningful, breaks no schema, and requires no frontend
change. (Rejected alternative: a per-source breakdown object — more information but a
larger schema/frontend change, not justified now.)

## 7. Error handling & edge cases

- **No earnings / gross == 0:** blended rate returns `0`, `available = 0`. No
  division by zero (guard on `total_cleared_gross == 0`).
- **Held / unreleased attestation escrow:** excluded from the attestation class (the
  existing `released_escrow_exists` predicate holds), so pre-settlement fees never
  count toward withdrawable balance.
- **Concurrent withdrawal:** `_lock_contributor_financials` advisory lock is unchanged
  and still serializes balance mutations across both earning classes.
- **Currency:** all sums are currency-scoped, as today. Attestation fees are USD in the
  current fee schedule; the per-currency structure is preserved.
- **Withdrawal below `$50`, no KYC, no 2FA:** handled by the existing payout path,
  unchanged. 6a adds nothing here.

## 8. Security

- No new endpoint, no new money movement, no escrow-path change → no new escrow
  sign-off surface. The escrow release remains the only place funds leave escrow, and
  it is untouched.
- Withdrawal gates (KYC, verified TOTP, `$50` minimum, audit) are inherited unchanged.
- Commission rate is read from `platform_config` (no secret), never logged as sensitive.
- Balance derivation is read-only aggregation; it creates no writable money state.

## 9. Testing (TDD, RED → GREEN per behavior)

**Unit — balance derivation (`_available_payout_balance`):**
1. Attestor with one released `attestation_fee` (fee F) → `available == F * 0.90`,
   available **immediately** (freezegun; no refund-window wait).
2. Mixed: user with a released attestation_fee (F) and a cleared framework purchase (P)
   → `available == F*0.90 + P*0.85 - claimed`.
3. Held / unreleased attestation_fee → excluded from balance (invariant preserved).
4. Framework/project-only earner → balance **byte-identical** to current behavior
   (regression guard; attestation branch contributes nothing).
5. Blended `commission_rate`: mixed earner → effective rate between 0.10 and 0.15;
   `gross == 0` → rate `0`, no `ZeroDivisionError`.
6. `attestation_commission_rate` config override (e.g. 0.12) → net reflects override.

**Integration — withdrawal of attestation earnings:**
7. Attestor with cleared attestation earnings requests payout → succeeds via the
   existing path (KYC + 2FA + `$50` min enforced); `net_amount` deducted from balance.
8. Attestor below `$50` attestation earnings → payout rejected by existing minimum.

## 10. Blast radius

- `financials/service.py`: `_available_payout_balance`, `_sum_transactions`
  (parameterize class filter), new `_attestation_commission_rate` loader.
- `financials/schemas.py`: `EarningsResponse.commission_rate` semantics (blended) —
  field unchanged, docstring updated.
- **No migration.** **No escrow change.** **No new endpoint.** **No new table.**
