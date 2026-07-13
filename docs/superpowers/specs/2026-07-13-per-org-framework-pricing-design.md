# Per-Organization Framework Pricing — Design Spec

**Date:** 2026-07-13
**Status:** Approved (grill-me complete)
**Scope:** Single-framework checkout only
**Maps to:** FR-FWK-\* (framework pricing), FR-FIN-\* (purchase flow)

---

## 1. Problem

Frameworks carry a single flat `price`. Organizations already exist as first-class
buyers — `create_org_framework_purchase` stamps `Transaction.payer_org_id`, mints an
org-owned `License` (`licensee_org_id`), and the org distributes access through the
existing `LicenseGrant` flow. But an org today can only buy the **`single_user`** tier
at the **same** flat price an individual pays, because:

- `frameworks.price` is one column — no per-tier price.
- The creation form exposes only `single_user` (`framework-form.tsx:41`; other tiers
  commented out).
- Both purchase paths hardcode `amount = _normalise_money(framework.price)`
  (`financials/service.py:1300`), ignoring `license_type`.

Sellers want to charge organizations a **different price** than individuals — while
allowing sellers who don't care to reuse the single-user price.

## 2. Goal

Let a seller offer an **organizational** license tier at its own price (or the same
price). Buyers choose **self** (single-user) or **a specific organization**
(organizational); the charge follows the selection. The feature is **invisible** on
frameworks that don't opt in.

## 3. Non-Goals (explicitly out of scope)

- **Seat metering.** Org license stays flat-price + uncapped grants. `seats_total` /
  `seats_used` remain latent columns for a future feature.
- **Team / enterprise tiers.** Only `single_user` + `organizational` are sellable.
- **Collections** (`create_collection_purchase`) and **Partner API**
  (`partner_service`) checkout — untouched, keep current flat behavior.
- Non-USD pricing (already blocked platform-wide).

---

## 4. Data Model

Add one nullable column to `frameworks`:

```
org_price  NUMERIC(12,2)  NULL
CHECK (org_price IS NULL OR org_price > 0)   -- ck_frameworks_org_price_positive
```

- Additive migration. **Zero backfill** — every existing row is `NULL`, and since no
  existing framework has `"organizational"` in `license_types`, behavior is unchanged.
- `upgrade`: add column + CHECK. `downgrade`: drop CHECK + column. Both must succeed.

### Tier switch

`license_types: ARRAY(LICENSE_TYPE_ENUM)` is the on/off switch (unchanged shape):

- `"single_user"` — **always present** (mandatory base tier).
- `"organizational"` — optional; presence ⇔ org tier is on sale.
- `org_price` semantics:
  - `"organizational"` absent → `org_price` **must** be `NULL` (else 422; see §7).
  - `"organizational"` present + `org_price` set → org tier priced at `org_price`.
  - `"organizational"` present + `org_price` `NULL` → org tier **reuses** `price`.

---

## 5. Charge Resolution

Single pure helper, used by **both** purchase paths so commission, payout split,
`Transaction.amount`, and invoices all inherit the resolved number with no other math
change.

```python
def resolve_license_price(framework: Framework, license_type: str) -> Decimal:
    """Charge amount for a license tier.

    Org tier falls back to the base price when `org_price` is NULL (seller chose to
    reuse the single-user price). All other tiers charge the base price.
    """
    if license_type == "organizational" and framework.org_price is not None:
        return framework.org_price
    return framework.price
```

Rules:

- `single_user` → always `framework.price`.
- `organizational` + `org_price` set → `org_price`.
- `organizational` + `org_price` NULL → `framework.price` (reuse).

Both callers replace the hardcoded amount line with:

```python
amount = _normalise_money(resolve_license_price(framework, payload.license_type))
```

Existing guard stays: `payload.license_type in framework.license_types`
(`service.py:1294`) — an org tier can never be charged unless the seller enabled it.

**Existing licenses are unaffected by later price edits** — the charged amount is
snapshotted into `Transaction.amount` at purchase.

---

## 6. Checkout — Buyer Context Coupled to Tier

License tier is **derived** from buyer context (no independent tier picker):

| Buyer selection | License type | Charge |
|-----------------|--------------|--------|
| Self | `single_user` | `price` |
| Organization | `organizational` | `org_price` (or `price` on reuse) |

Changes to `checkout-form.tsx` + `purchase-context.ts`:

- **Drop the license-type radio group.** Buyer selector is the only control.
- `eligibleOrgBuyers` gains a gate: an org buyer is listed **only when**
  `framework.license_types.includes("organizational")` **AND** the org is eligible
  (`role ∈ {owner, admin}` AND `capabilities.operator === "active"`) — existing
  eligibility unchanged, plus the tier-availability gate.
- Self-only case (no tier-matching eligible org) → no selector, plain single-user
  checkout, **identical to today**.
- Display the resolved tier label + price for the current selection: self → base;
  org → `org_price`, or `"$X — same as single user"` when reused.

**Net effect:** on every framework that hasn't opted into the org tier (all existing
ones), checkout renders exactly as it does now. The feature only appears when a seller
opts a framework in AND the buyer admins an eligible org.

Backend re-validates buyer capability + admin role (client gate is UX only) — unchanged.

---

## 7. Validation

| Case | Rule |
|------|------|
| Orphan price: `org_price` set, `"organizational"` ∉ `license_types` | **422 reject** (`error_code: org_price_without_org_tier`). No silent null. |
| Positivity | Pydantic `gt=0` on input + DB `CHECK (org_price IS NULL OR org_price > 0)`. |
| `org_price` vs `price` ordering | **No constraint** — seller may price org below base (bulk framing). Their call. |
| `"organizational"` present, `org_price` NULL | **Allowed** — means "reuse base price". |

### Edit semantics (existing framework)

- **Add org tier later** — allowed anytime (set `"organizational"` + optional `org_price`).
- **Change `org_price`** — forward-only; applies to future org purchases. Existing org
  licenses unaffected (snapshotted).
- **Remove org tier** (drop `"organizational"`) — service **nulls `org_price`** in the
  same write (keeps orphan-reject invariant satisfiable). Allowed **even with active
  org licenses** — those are settled purchases, not subscriptions; only future org
  sales stop.

---

## 8. Display Surfaces

| Surface | Behavior |
|---------|----------|
| Explore card (`framework-list.tsx:258`) | Base (single_user) price only. **Unchanged.** |
| Framework detail (`explore/[id]/page.tsx:99`) | "Starting price" = base. Add a second line **only when org tier offered**: `Organizational — $Y`, or `Organizational — $X (same as single user)` on reuse. |
| Checkout | Resolved price for the selected buyer (self → base; org → org price / reuse). One price at a time. |

---

## 9. API Contract

- Add `org_price: Decimal | None` to:
  - Framework **response** schema (detail + checkout read it).
  - Pricing **input** schema (creation/edit write it), with `gt=0` + `decimal_places=2`
    + `max_digits=12`.
- Update `contracts/openapi.yaml`, then regenerate the frontend client
  (`lib/generated/*`).

---

## 10. Creation / Edit Form

`framework-form.tsx`:

- Uncomment / restore the `organizational` license-type option. `single_user` stays
  mandatory (cannot be unchecked).
- When `organizational` is checked, reveal an **optional** `org_price` field, helper:
  "Leave blank to charge the same as the single-user price."
- On submit: send `org_price` only when the org tier is selected; the service enforces
  the orphan-reject rule (§7) and the null-on-removal rule.
- `team` / `enterprise` stay commented out (out of scope).

---

## 11. Logging

Per standard, `module="financials"` / `module="frameworks"`:

- `purchase_initiated` / `escrow_funded` entries already exist — include resolved
  `license_type` + `amount` (already logged) so org-tier charges are auditable.
- Framework create/edit already logs; ensure `org_price` presence is captured in the
  edit path's structured context (not the value alone — value is fine, it is not PII).

---

## 12. Testing (TDD, RED→GREEN per behavior)

**Backend unit (`resolve_license_price` + service):**
- `single_user` → base price.
- `organizational` + `org_price` set → `org_price`.
- `organizational` + `org_price` NULL → base price (reuse).
- Orphan `org_price` (no org tier) → 422 on create/edit.
- `org_price` ≤ 0 → 422.
- Removing org tier on edit nulls `org_price`.
- Removing org tier with an active org license succeeds; existing license unchanged.

**Backend integration (endpoints):**
- Org purchase of an org-tier framework charges `org_price` (assert `Transaction.amount`).
- Org purchase where `org_price` NULL charges base price.
- Self purchase always charges base price.
- Buying a tier not in `license_types` → 422 (guard intact).

**Frontend (vitest + RTL):**
- Detail shows the org-price line only when tier offered; shows "same as single user"
  on reuse.
- Checkout lists an org buyer only when framework offers the org tier AND org eligible.
- Single-user-only framework → no org buyer, no tier picker (unchanged render).
- Buyer=org selection drives the displayed price to `org_price`.

**E2E (playwright, 375px):**
- Seller enables org tier with a distinct price → org admin buys → charged org price →
  org holds the license.

---

## 13. Migration & Rollback

- One additive Alembic migration: add `org_price` + CHECK. Filename
  `2026_07_13_add_framework_org_price.py`.
- `alembic upgrade head` and `alembic downgrade -1` both succeed.
- No data backfill. Backwards-compatible with the previously deployed version
  (column nullable, code tolerates NULL as "reuse / not offered").

---

## 14. Risk & Security

- **Money path touched** — charge resolution changes the amount a buyer is billed.
  Mitigated by: single pure resolver with exhaustive unit tests; existing
  `license_type ∈ license_types` guard; amount snapshotted per transaction.
- No new external surface, no new dependency, no secret handling.
- Client-side buyer/tier gating is UX only; backend re-validates capability + role and
  the tier guard, per platform rule (client checks are never trusted).
- Org price is not PII; safe to log at INFO with existing purchase context.
