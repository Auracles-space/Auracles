# Attestation Module 6d — Invoicing — Design

**Date:** 2026-07-02
**Build priority:** 6 (Settlement & Payout), sub-module **d** of 4 (final).
**Status:** Approved for planning.

## 0. Module 6 decomposition (recap)

| Sub-module | Scope | Workflow |
| ---------- | ----- | -------- |
| 6a Settlement | Escrow settles at 90/10; attestor earnings clear immediately. | §6.1, §6.2 |
| 6b Reputation | Attestor reputation subject; Certified Attestor L5; feed AMM. | §6.4 |
| 6c Badge & Provenance | Version-locked badge, completed-attestations list, provenance. | §6.3 |
| **6d Invoicing** (this doc) | Attestation tax invoice (requestor) + earnings statement (attestor) + annual earnings summary. | §6.5 |

## 1. Overview

6d closes the attestation loop with its **documents**. Workflow §6.5: a tax invoice for
the Requestor (full fee), an earnings statement for the Attestor (90% share), both stored
in the Financials module, plus annual earnings summaries each January for tax purposes.

**Scope expanded deliberately (architect decision).** Rather than bolt attestation-only
invoices onto the existing minimal purchase-invoice renderer, 6d introduces a **shared,
tax-compliant `invoicing` module** used by *both* the framework marketplace and
attestation, and retrofits framework purchase invoices onto it. This fixes the
platform-wide invoicing gap once (gapless numbering, immutable issued-invoice ledger,
seller identity block, tax line) instead of half-building it inside an attestation
sub-module. Tax *determination* (Stripe Tax) is registration-gated and explicitly
deferred — see `docs/post-registration-checklist.md`.

## 2. Scope boundary

**In scope:**
- New `app/modules/invoicing/` module: immutable `Invoice` ledger + gapless number
  allocator + shared WeasyPrint render.
- Attestation **tax invoice** (full fee) — lazy-on-GET endpoint, requestor + admin.
- Attestation **earnings statement** (90% remittance) — lazy-on-GET endpoint, attestor +
  admin.
- Attestation **annual earnings summary** — Celery Beat batch (early January, prior full
  calendar year), stored in S3 + email notification, fetch endpoint.
- **Retrofit** the existing framework purchase invoice onto the `invoicing` module
  (forward-only).
- Seller-identity config block; config-driven tax line (default 0%).

**Out of scope (deferred / other modules):**
- **Stripe Tax / real tax determination** — registration-gated; recorded in
  `docs/post-registration-checklist.md`. 6d ships the tax *line* (config rate default 0%),
  not a jurisdiction VAT engine.
- **Historical purchase backfill** — retrofit is forward-only (issue on next GET).
- Any change to escrow, settlement (6a), badge (6c), reputation (6b), or payout flows.
- Frontend — backend-only module (endpoints + OpenAPI). Frontend consumes later.
- Recipient-created / self-billing tax invoices (RCTI) — the attestor doc is a
  remittance/earnings **statement**, not a tax invoice issued on the attestor's behalf.

## 3. What already exists (reused)

- **Purchase invoice pipeline** — `financials/invoices.py:purchase_invoice_key`,
  `workers/tasks/financials.py:generate_invoice_pdf` (+ `INVOICE_TEMPLATE`), lazy retrieval
  `financials/service.py:get_framework_purchase_invoice` (302 presigned if S3 object
  exists, else `.delay()` + 202). Retrofitted, not duplicated.
- **Attestation fee transaction** — `attestation/service._fund_attestation` creates a
  `Transaction` with `transaction_type="attestation_fee"`, `ref_type="attestation"`,
  `ref_id=attestation_id`, `payer_id=requestor`, `payee_id=None`, `amount`=full fee,
  `currency="USD"`. This is the tax-invoice data source. Attestor resolved via
  `Attestation.attestor_id`.
- **Commission rate** — `financials/service._attestation_commission_rate` (config
  `attestation_commission_rate`, default `Decimal("0.10")`) via `_platform_decimal_config`.
  Earnings-statement net = `amount × (1 − rate)`; effective rate printed.
- **Settlement signal** — an attestation is settled when `status="closed"` /
  `report_published_eligible = True` (stamped in Module 5 / 6a on accept, auto-accept,
  dispute-rejected) **and** its escrow is `released`.
- **WeasyPrint** — worker image already carries Cairo/Pango (Phase 3). No new image deps.
- **S3 reports bucket** — `settings.s3_reports_bucket`, private, presigned GET
  (`s3.storage.object_exists` / `presigned_get` / `upload_bytes`).
- **Email/notification** — existing Resend + notification system (used by other Beat
  jobs) for the annual-summary "ready" email.
- **Celery Beat** — `workers/beat_schedule.py` (crontab entries). Annual job added here.

## 4. The `invoicing` module

`app/modules/invoicing/{models,service,render,schemas}.py`. New tables via one Alembic
migration.

### 4.1 `Invoice` — immutable issued-invoice ledger

`invoicing` table. Once inserted, **never mutated** (compliance: an issued invoice is
frozen). Columns:

| Column | Notes |
| ------ | ----- |
| `id` (UUID PK) | |
| `series` | `AUR-INV` (sales) \| `AUR-ERN` (earnings statement) |
| `sequence_year` (int) | year the number was allocated in |
| `sequence_number` (int) | gapless within `(series, sequence_year)` |
| `invoice_number` (str) | rendered form, e.g. `AUR-INV-2026-000123`; unique |
| `doc_type` | `sales_invoice` \| `earnings_statement` |
| `issue_date` (timestamptz) | allocation time |
| `currency` (char3) | |
| `subtotal` (Numeric 12,2) | |
| `tax_rate` (Numeric 5,4) | snapshot of `invoice_tax_rate` at issue |
| `tax_amount` (Numeric 12,2) | |
| `total` (Numeric 12,2) | `subtotal + tax_amount` |
| `commission_rate` (Numeric 5,4, nullable) | earnings statements only — effective rate |
| `net_amount` (Numeric 12,2, nullable) | earnings statements only — attestor 90% |
| `seller_name` / `seller_tax_id` / `seller_address` | seller snapshot at issue (from config) |
| `buyer_name` / `buyer_email` | party snapshot |
| `source_ref_type` (str) | `transaction` (purchase) \| `attestation` |
| `source_ref_id` (UUID) | |
| `s3_key` (str) | deterministic; `invoices/{doc_type}/{id}.pdf` |
| `created_at` | |

Constraints:
- `UNIQUE (series, sequence_year, sequence_number)` — gapless register integrity.
- `UNIQUE (invoice_number)`.
- `UNIQUE (source_ref_type, source_ref_id, doc_type)` — **idempotency**: one issued doc
  per source per type; re-issue attempts return the existing row.
- `CHECK (subtotal >= 0)`, `CHECK (total >= 0)`, `CHECK (tax_rate >= 0)`.

### 4.2 `invoice_counters` — gapless allocator

`invoice_counters` table: PK `(series, year)`, column `last_number` (int, default 0).

`issue_invoice(...)` runs **inside one transaction**:
1. `SELECT last_number FROM invoice_counters WHERE series=:s AND year=:y FOR UPDATE`
   (insert the row at 0 first if absent — `ON CONFLICT DO NOTHING` then re-select).
2. `last_number += 1` → `sequence_number`.
3. Insert the frozen `Invoice` row with that number + snapshots.
4. Commit. Abort at any step un-allocates the number (row lock released, `last_number`
   unchanged) → **truly gapless**.

Idempotency: before allocating, `SELECT` the `Invoice` by
`(source_ref_type, source_ref_id, doc_type)`; if present, return it (no new number).
The unique constraint is the backstop against a race (catch → re-select).

### 4.3 `invoicing.service`

- `issue_invoice(db, *, doc_type, series, source_ref_type, source_ref_id, currency, subtotal, seller, buyer, commission_rate=None, net_amount=None) -> Invoice`
  — idempotent allocate + snapshot + persist (§4.2). Computes `tax_rate` from
  `invoice_tax_rate` config (default `Decimal("0")`), `tax_amount = subtotal * tax_rate`
  (quantized), `total`, `s3_key`. Pure DB; no PDF, no S3.
- `get_or_none(db, *, source_ref_type, source_ref_id, doc_type) -> Invoice | None`.

Seller block from config: `INVOICE_SELLER_NAME`, `INVOICE_SELLER_TAX_ID`,
`INVOICE_SELLER_ADDRESS` (settings; placeholder defaults for dev — real via env at
registration). `invoice_tax_rate` is a `platform_config` decimal key (default 0) via
`_platform_decimal_config`.

### 4.4 `invoicing.render`

Two WeasyPrint templates rendering **only from a frozen `Invoice` row** (never recompute):
`sales_invoice.html` (subtotal / tax / total, seller + buyer block, source line) and
`earnings_statement.html` (gross fee, commission rate + amount, net remittance). Function
`render_invoice_pdf(invoice, extra_context) -> bytes`. `extra_context` supplies the human
line item (framework title / attestation review-type) the ledger row doesn't store.

## 5. Endpoints (attestation router; lazy 302/202)

All follow the existing purchase-invoice retrieval shape: check S3 → 302 presigned if
present, else issue (if needed) + enqueue render + 202.

| Endpoint | Auth | Behavior |
| -------- | ---- | -------- |
| `GET /v1/attestation/{attestation_id}/invoice` | requestor of the attestation, or admin | 409 unless settled (`closed`/`report_published_eligible` + released escrow). Resolve `attestation_fee` txn → `issue_invoice(doc_type=sales_invoice, series=AUR-INV, subtotal=fee)` → render task → 302/202. |
| `GET /v1/attestation/{attestation_id}/earnings-statement` | attestor of the attestation, or admin | 409 unless settled. `issue_invoice(doc_type=earnings_statement, series=AUR-ERN, subtotal=fee, commission_rate=rate, net_amount=fee*(1-rate))` → render → 302/202. |
| `GET /v1/attestation/earnings/annual/{year}` | attestor (own summary) | 302 if `annual-summaries/{attestor_id}/{year}.pdf` exists; else 404 if `year` not yet generated / no earnings (summary is Beat-produced, not lazily issued). Admin may fetch any attestor's via query? — no; strict own-only. |

- **RBAC at dependency layer.** Party membership (`requestor_id` / `attestor_id`) checked
  in an attestation dependency, never in service. Admin override via the approved-admin
  `UserRole` query pattern (as 6c), **audit-logged** on every admin fetch of another
  party's doc.
- **Not-settled → 409** ("Invoice is only available for settled attestations"), mirroring
  the purchase-invoice 409.
- **Cross-party denial → 403** (requestor cannot fetch earnings statement; attestor cannot
  fetch tax invoice), logged WARNING with `user_id` + attempted action.

## 6. Annual earnings summary (derived report — NOT a ledger invoice)

- **Beat task** `app.workers.tasks.invoicing_beat.generate_annual_earnings_summaries`,
  schedule `crontab(month_of_year=1, day_of_month=2, hour=6, minute=0)` (Jan 2, 06:00 UTC —
  avoids the midnight settlement-timestamp boundary).
- Covers the **prior full calendar year**. Enumerates attestors with ≥1 settled
  `attestation_fee` (released escrow) whose settlement/issue falls in that year. Zero-earner
  attestors get nothing.
- Per attestor: render one PDF — identity, year, line items (settled date, attestation id,
  review type, gross fee, effective rate, net), year totals (gross, net, count). USD
  (per-currency grouping only if a non-USD fee ever appears).
- **Not numbered, not in the `Invoice` ledger** — a regenerable aggregate of already-issued
  data. Deterministic key `annual-summaries/{attestor_id}/{year}.pdf`; re-run **overwrites**
  (idempotent).
- After upload, enqueue an **email notification** ("Your {year} earnings summary is ready")
  via the existing notification/Resend path. Email links to the fetch endpoint — **never** a
  presigned URL in the email body.
- Task is idempotent and safe to re-run (Beat retry, manual `.apply()`): same inputs →
  same PDFs at the same keys; notification send guarded against duplicates per
  `(attestor, year)`.

## 7. Retrofit — framework purchase invoice

- `financials.service.get_framework_purchase_invoice` switches to the `invoicing` service:
  on GET of a settled (`completed`/`refunded`) purchase, `issue_invoice(doc_type=
  sales_invoice, series=AUR-INV, source_ref_type=transaction, source_ref_id=txn_id,
  subtotal=amount, seller=config, buyer=operator)` (idempotent) → render via
  `invoicing.render` → new deterministic key `invoices/sales_invoice/{invoice_id}.pdf`
  → 302/202.
- **Forward-only.** No historical backfill. Numbers allocate in **issue order** (first
  fetch), gapless from the register's start — legally sufficient. Legacy
  `invoices/purchases/{txn_id}.pdf` objects are left as harmless dead objects.
- Purchase + attestation tax invoices thus share the `AUR-INV` register and the same
  seller block + tax line → uniform across the platform.
- **Regression guard:** the purchase-invoice endpoint contract (409 gate, 302/202, auth)
  stays behaviorally identical; only the renderer + key + numbering change.

## 8. Error handling & edge cases

| Case | Handling |
| ---- | -------- |
| Attestation not settled | 409 |
| Cross-party fetch | 403 + WARNING log |
| Unauthenticated | 401 |
| Attestation / txn not found | 404 |
| Re-issue (doc already exists) | return existing `Invoice`, no new number (idempotent) |
| Concurrent first-fetch (race on issue) | unique `(source_ref_type, source_ref_id, doc_type)` → catch, re-select existing |
| Concurrent allocation, same series | `FOR UPDATE` serializes; gapless preserved |
| Render task failure | Celery retry (`countdown=60`, `max_retries=3`), as existing PDF tasks |
| Annual year with no earners | no PDF, no email; endpoint 404 for that year |
| Non-USD fee | per-currency grouping preserved; current schedule USD-only |
| Tax rate 0 | line prints `Tax (0%): 0.00`; `tax_amount=0`, `total=subtotal` |

## 9. Security

- **No new money movement, no escrow change.** Invoicing is read-only over settled
  transactions; it writes only the immutable `Invoice` ledger (a document record, not a
  balance). No new escrow sign-off surface.
- **RBAC at dependency layer**; strict party membership; admin access audit-logged.
- **Presigned URLs only** for PDF delivery (15-min TTL), never proxied; never logged in
  full (log `invoice_id` / `attestation_id`, never the presigned URL).
- **Seller config** (`INVOICE_SELLER_*`) is non-secret identity; `invoice_tax_rate` is
  config. No secrets in code/logs.
- **Audit trail:** invoice issued (first time a number is allocated), admin cross-party
  fetch, annual-summary generation. Log with `module="invoicing"` / `module="attestation"`,
  action, `user_id`, `invoice_number` / `attestation_id`.
- **PII:** buyer/seller names + emails are on the invoice by necessity; never surfaced in
  any list endpoint, only on the party's own document.

## 10. Testing (TDD, RED → GREEN per behavior)

**Unit — `invoicing.service` allocator:**
1. First issue for a series/year → `sequence_number == 1`, `invoice_number ==
   "AUR-INV-2026-000001"`.
2. Second issue same series/year → `2`; **gapless** consecutive.
3. Rollback mid-issue (inject failure after allocate) → next issue reuses the number (no
   gap).
4. Idempotent: two `issue_invoice` for same `(source, doc_type)` → same row, number
   allocated once.
5. Per-year reset: issue in 2026 then 2027 → 2027 restarts at `1`.
6. Tax line: `invoice_tax_rate=0` → `tax_amount=0`, `total=subtotal`; override `0.075` →
   `tax_amount = subtotal*0.075` quantized, `total` correct.
7. Earnings statement: `net_amount == subtotal*(1-rate)`, `commission_rate` snapshotted.

**Unit — render:** frozen `Invoice` row renders both templates without recompute; seller
block from config; earnings statement shows gross/rate/net.

**Integration — endpoints:**
8. Requestor GET tax invoice on settled attestation → 202 then 302 (object exists after
   task); unsettled → 409; attestor GET tax invoice → 403; stranger → 403/404.
9. Attestor GET earnings statement → 202→302; requestor → 403.
10. Admin GET either → allowed + audit log written.
11. Purchase-invoice retrofit: settled purchase GET → compliant invoice issued (number
    allocated, new key), contract identical (409 unsettled, 302/202); **regression** — the
    existing purchase flow still passes.

**Celery — annual summary (`task.apply()`, freezegun):**
12. Jan-2 run over a prior year with 2 earner attestors → 2 PDFs at deterministic keys +
    2 notifications; zero-earner attestor → no PDF.
13. Idempotent: run twice → same keys overwritten, no duplicate notification.
14. Endpoint: attestor GET own `{year}` → 302 after generation; other attestor's → 403/404.

**Migration:** `alembic upgrade head` + `downgrade -1` create/drop `invoicing` +
`invoice_counters` cleanly.

## 11. Blast radius

- **New:** `app/modules/invoicing/` (models, service, render, schemas); one Alembic
  migration (2 tables); `app/workers/tasks/invoicing_beat.py`; Beat schedule entry;
  attestation router endpoints + schemas; settings `INVOICE_SELLER_*`; `invoice_tax_rate`
  config key (code default, no seed migration).
- **Changed:** `financials/service.get_framework_purchase_invoice` (retrofit to
  `invoicing`); purchase render moves to shared templates (old `generate_invoice_pdf` /
  `INVOICE_TEMPLATE` retired or delegated). `contracts/openapi.yaml`.
- **Unchanged:** escrow, settlement (6a), balance derivation, payout, badge (6c),
  reputation (6b), all money movement.

## 12. Build slices (backend-only, TDD, one at a time)

1. `invoicing` models (`Invoice`, `invoice_counters`) + migration + gapless idempotent
   `issue_invoice` service + `invoice_tax_rate`/seller config. (Unit: gapless,
   rollback-safe, idempotent, per-year reset, tax line.)
2. Shared render (`sales_invoice` + `earnings_statement` templates) from frozen row.
3. Retrofit framework purchase invoice onto `invoicing` (forward-only, new key,
   regression-guarded).
4. Attestation tax-invoice endpoint (lazy 302/202, requestor + admin, 409 gate) + render
   task.
5. Attestation earnings-statement endpoint (attestor + admin) + render task.
6. Annual summary Beat task (Jan-2, prior-year earners) + render + email notification +
   fetch endpoint + idempotent key.
7. OpenAPI contract for all new endpoints.
