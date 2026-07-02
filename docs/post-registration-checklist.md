# Post-Registration Checklist

Actions that are **blocked until the company is legally registered** (before product launch).
Deferred deliberately during build; recorded here so they are not forgotten.

Convert relative context to absolute: created 2026-07-02 during Attestation Module 6d
(invoicing) design.

---

## Invoicing / Tax

Introduced by Module 6d (shared `invoicing` module). The invoicing **infrastructure**
(gapless numbering, immutable `Invoice` ledger, seller block, tax line) ships now with a
config-driven tax rate defaulting to `0%`. The following require the registered entity
and/or tax registration and must be done post-registration:

- [ ] **Fill real seller identity config** — set `INVOICE_SELLER_NAME`,
  `INVOICE_SELLER_TAX_ID`, `INVOICE_SELLER_ADDRESS` (and any registration number) to the
  registered legal entity values in production env / Secrets Manager. Placeholders used
  pre-registration.
- [ ] **Enable Stripe Tax** (industry-standard tax determination for the marketplace).
  Replaces the flat config `tax_rate`. Feeds real per-buyer `tax_rate` / `tax_amount`
  into the existing immutable `Invoice` ledger — no schema change expected, the columns
  already exist. Scope as its own spec: buyer-country × B2B/B2C × reverse-charge ×
  digital-services (OSS/VATMOSS) determination is Stripe Tax's job, not hand-rolled.
  Requires: registered entity, Stripe Tax enabled on the account, tax settings configured.
- [ ] **Set the live tax rate config** (interim, only if charging tax before Stripe Tax is
  wired) — flip the `invoice_tax_rate` config key from `0` to the applicable rate.
- [ ] **Backfill decision** — issued invoices are immutable. Decide whether pre-tax-rate
  invoices need any reissue/credit-note treatment once tax goes live (likely no; new rate
  applies going forward).

## Licensing / IP

- [ ] **Update license copyright** — from "William Ikeji and contributors" to the
  registered company, once IP assignment completes (PolyForm Noncommercial 1.0.0).
  See memory `project_license`.
