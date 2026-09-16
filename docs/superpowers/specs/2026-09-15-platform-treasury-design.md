# Platform Treasury — design

Admin Treasury page and platform withdrawals. It answers four questions: how much of
the money we hold belongs to users, how much is ours, how much of ours we can withdraw
now, and how much we have already withdrawn. It also gives the platform a safe way to
move its own money to its own bank account.

Decisions came from the grill-me review on 2026-09-15 and the human approved all of them
(§Decisions). Maps to: FR-FIN (financials) and FR-ADMIN (admin module).

## Why

- Paystack does not settle to a bank on a schedule. Every naira collected (purchases,
  escrow, attestation fees) stays in one Paystack balance. Contributor payouts, org
  payouts, partner payouts and escrow releases all come out of that same balance.
- Nothing in that balance marks which money is ours. Today the only guard is
  `financials/balance_floor.py`, which pages an admin when the balance drops below held
  escrow. It ignores user balances that have already been released, and it knows nothing
  about the platform's share.
- Money can leave the balance without Auracles knowing. Anyone with Paystack dashboard
  access can start a transfer. `webhooks/service.py::_payout_for_transfer` returns
  `None` for a transfer it does not recognise, and the handler then does nothing.
- Provider fees are not recorded anywhere, so the platform's real earnings are
  overstated.

## Decisions (locked 2026-09-15)

| # | Decision |
|---|---|
| 1 | v1 covers Paystack/NGN for the live balance and for withdrawals. Every total comes from the ledger. Stripe money is shown as ledger-only and labelled "not withdrawable here". |
| 2 | Withdrawable = min(our unwithdrawn money, live Paystack balance − everything owed to users). |
| 3 | One platform bank account, stored encrypted and shown as the last 4 digits only. Only the super-admin can set or change it, and only with step-up. A changed account cannot receive a withdrawal for 24h. Every change is audited and emailed to all admins. |
| 4 | Only the super-admin can withdraw, and only with step-up. Every admin gets an email for each withdrawal. |
| 5 | Paystack transfers that Auracles did not start are recorded, shown on Treasury, and trigger an instant alert to all admins. A balance-gap warning is shown as well. |
| 6 | The platform absorbs Paystack fees and records them as costs. Our money = commission − provider fees − partner commissions − platform withdrawals. |
| 7 | Fees on past charges are backfilled once, through a new Paystack transaction lookup. |
| 8 | A failed withdrawal returns its amount to available. It is marked Failed with Paystack's reason, all admins are alerted, and it is never retried automatically. Only one withdrawal can be in flight at a time. |
| 9 | Every admin can view Treasury. Only the super-admin can change anything. |
| 10 | Withdrawal minimum is ₦10,000, stored as `min_platform_withdrawal_ngn` and editable by the super-admin. There is no maximum below available and no daily cap. |
| 11 | Monthly CSV statement per Lagos-time (WAT) calendar month (§Statement). |
| 12 | Provider fees are stored in their own table, not as a column on `transactions`. |

## Definitions (Paystack, NGN)

"Settled" uses the same status predicates as the existing balance code
(`_sum_transactions`, `_sum_org_transactions`, `_claimed_payouts`,
`_claimed_org_payouts`). Treasury must not create its own definition. A test asserts
that the aggregate figure equals the sum of the per-account balances.

**Owed to users (liabilities)**
- Held escrow: `escrows.status = 'held'` on Paystack transactions.
- Contributor balances: net credited to individuals (pending clearance + available)
  − payouts `completed`.
- Org balances: net credited to orgs − org payouts `completed`.
- In-flight user payouts: payouts in `pending|processing` are still in the balance.
  They are already covered by the two lines above, because only `completed` is
  subtracted.
- Partner money: partner commissions in `pending|cleared` + partner payouts in
  `pending|processing`, not yet paid.

**Our money**
- Commission: Σ `transactions.platform_commission` on settled, non-refunded
  transactions, split by source (framework sale, collection, project milestone,
  attestation fee).
- − Provider fees: Σ `provider_fees.amount`.
- − Partner commissions: Σ `partner_commissions.commission_amount` where status ≠
  `voided`. These are funded from our commission, so seller net is untouched.
- − Platform withdrawals: Σ `platform_withdrawals.amount` in `processing|completed`,
  plus each withdrawal's own transfer fee through `provider_fees`.

**Withdrawable** = `max(0, min(our_money, paystack_balance − owed_to_users))`, rounded
down to the kobo.

**Balance gap** = `paystack_balance − (owed_to_users + our_money)`.
- Negative beyond ₦1 tolerance: money is missing. Show a red warning and alert admins
  (hourly, deduped per day, reusing the balance-floor alert pattern).
- Positive: money is unexplained (for example a manual top-up). Show an info note with no
  alert.

**Withdrawn**: completed withdrawals, all-time and this month, with history.

**Stripe**: the same ledger lines per currency (USD etc.). No live balance, no
withdrawable figure, no gap.

## Data model

Migration 0111 onward, one migration per slice.

### `provider_fees` (0111)

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| provider | enum `stripe\|paystack` | v1 writes paystack only |
| source_type | enum `transaction\|payout\|partner_payout\|platform_withdrawal` | |
| source_id | uuid | not a FK (polymorphic); indexed with source_type |
| amount | numeric(12,2) | major units |
| currency | char(3) | |
| provider_ref | varchar(255) | charge reference or transfer code |
| origin | enum `webhook\|backfill` | |
| occurred_at | timestamptz | provider time, used for statement months |
| created_at | timestamptz | |

- A unique constraint on `(provider, source_type, provider_ref)` makes webhook retries
  and the backfill idempotent. It is keyed by reference rather than `source_id`, so a
  double charge (a second, distinct charge on one transaction) records its second
  real fee.
- A charge fee is recorded even when local settlement refuses the charge (amount
  mismatch, double charge): the money reached the balance and Paystack kept its fee.
- Refunds do not reverse a fee, because Paystack keeps the charge fee. A refunded sale's
  fee stays as a cost.

### `platform_bank_accounts` (0112)

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| provider | enum | paystack |
| bank_code, bank_name | varchar | |
| account_last4 | char(4) | only display field |
| account_name | varchar | name Paystack resolved from the bank |
| recipient_code_encrypted | text | Paystack transfer recipient |
| usable_from | timestamptz | `created_at + 24h` |
| created_by | uuid FK users | |
| created_at | timestamptz | |
| replaced_at | timestamptz null | |

- The full account number is not stored: withdrawals need only the encrypted recipient
  code, and display needs only the last 4 digits.
- The 24h hold applies to the first account too, since a hijacked first setup is as
  dangerous as a change.
- At most one row has `replaced_at IS NULL` (partial unique index).
- A change inserts a new row and stamps `replaced_at` on the old one. Rows are never
  updated in place, so history is kept.

### `platform_withdrawals` (0113)

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| bank_account_id | uuid FK platform_bank_accounts | |
| amount | numeric(12,2) | |
| currency | char(3) | NGN |
| status | enum `pending\|processing\|completed\|failed` | |
| provider_ref | varchar(255) unique | `platform-withdrawal-<id>` |
| failure_reason | text null | |
| requested_by | uuid FK users | |
| requested_at, completed_at, failed_at | timestamptz | |

- A partial unique index on `(currency) WHERE status IN ('pending','processing')`
  enforces one withdrawal in flight at the database level.

### `unrecognized_transfers` (0114)

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| provider | enum | |
| provider_ref | varchar(255) unique | transfer reference/code |
| event_type | varchar | transfer.success / failed / reversed |
| amount, currency | | |
| recipient_last4 | char(4) null | only if the payload carries it |
| acknowledged_by, acknowledged_at | null | admin marks "reviewed" |
| created_at | timestamptz | |

### Config

- `min_platform_withdrawal_ngn` = 10000, seeded in 0113.
- Added to `EDITABLE_PLATFORM_CONFIG_KEYS`, but editing it requires the super-admin
  (checked in the admin config dependency, not in the service).

## Money flows

### Fees from webhooks
- `charge.success` (purchase, escrow, attestation fee): record `data.fees` (kobo) against
  the transaction, in the same DB transaction that settles it.
- `transfer.success` for a Payout, PartnerPayout or PlatformWithdrawal: record the
  transfer fee against that row.
  - **Open item A:** confirm which field Paystack's test mode sends for the transfer fee.
    If none is sent, fetch the transfer by code after success, in a Celery task with
    retry.

### Withdrawal
1. `POST /v1/admin/treasury/withdrawals` `{amount}`. The router applies
   `require_superadmin` and step-up.
2. Service, inside one DB transaction:
   1. Take the advisory lock `platform_treasury:NGN`.
   2. Load the active bank account. None → 422 `platform_bank_account_missing`.
      `usable_from > now` → 422 `platform_bank_account_on_hold`.
   3. If a withdrawal is in flight → 409 `platform_withdrawal_in_progress`.
   4. If amount < the minimum → 422 `below_minimum_withdrawal`.
   5. Fetch the live balance. A provider error → 502 and no row is written.
   6. Compute withdrawable. amount > withdrawable → 402 `insufficient_withdrawable` plus
      an audit row.
   7. Insert the `pending` row and audit `platform_withdrawal_requested`.
3. After commit, dispatch the Celery task. It calls `paystack.initiate_transfer` with the
   reference `platform-withdrawal-<id>` and sets `processing`. It is idempotent: it skips
   unless the row is `pending`. Transient errors retry with a 60s countdown. A
   definitive rejection marks the row `failed`.
4. `transfer.success` → `completed`, fee recorded, all admins emailed.
5. `transfer.failed|reversed` → `failed` with the reason. The amount returns to available
   automatically because only `processing|completed` count. All admins are alerted.
   Nothing is retried.
6. Admins are emailed at request, completion and failure. Emails show amount, last 4 and
   reference only.

### Unrecognized transfer
- In the Paystack transfer branch, a reference that matches no Payout, PartnerPayout or
  PlatformWithdrawal (by `provider_ref`, then metadata) is inserted into
  `unrecognized_transfers` (idempotent on `provider_ref`).
- After commit, all admins get an instant email and in-app notice (domain
  `treasury_alert`, link `/admin/treasury`).
- Logged at CRITICAL (`unrecognized_transfer_detected`).
- The Stripe path keeps its current no-op. Out of scope for v1.

### Bank account change
- `PUT /v1/admin/treasury/bank-account` `{account_number, bank_code}` requires the
  super-admin and step-up.
- Paystack resolves the account and creates the recipient first. A failure → 502 and
  nothing is stored.
- The new row is then written, the old one is stamped replaced, and
  `platform_bank_account_changed` is audited (last 4 old and new).
- All admins are emailed: "withdrawals to this account open at <time WAT>".
- A withdrawal in flight is not affected. It keeps its original account.

### Fee backfill
- New `paystack.fetch_transaction(reference)` using `_get_json`
  (`GET /transaction/verify/:reference`).
- Triggered by a one-off Celery task from a super-admin action
  (`POST /v1/admin/treasury/fee-backfill`, step-up, 202). It walks settled Paystack
  transactions that have no fee row, in batches, with a rate limit of 5 requests/s.
- It is idempotent through the unique constraint. It records `origin=backfill` and audits
  the counts.

## API

All endpoints live under `/v1/admin/treasury`. View endpoints need the admin role and
action endpoints need the super-admin. Every response model is explicit and shows no
full account number or recipient code.

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/summary` | admin | Owed to users (by line), our money (by line), withdrawable, withdrawn, gap, live balance + fetched_at, Stripe ledger lines. Balance fetch failure → figures still returned, `live_balance: null`, `withdrawable: null`, flag `balance_unavailable`. |
| GET | `/withdrawals` | admin | Paginated history |
| POST | `/withdrawals` | super-admin + step-up | Request withdrawal |
| GET | `/bank-account` | admin | Bank name, last 4, account name, usable_from |
| PUT | `/bank-account` | super-admin + step-up | Set or replace |
| GET | `/unrecognized-transfers` | admin | List |
| POST | `/unrecognized-transfers/{id}/acknowledge` | super-admin | Mark reviewed (audited) |
| GET | `/statements/{yyyy-mm}.csv` | admin | Monthly statement, audited `treasury_statement_downloaded` |
| POST | `/fee-backfill` | super-admin + step-up | Queue backfill (202) |

Every action writes an audit row. Non-super-admin action attempts → 403
`superadmin_required`, logged at WARNING by the existing dependency.

## Statement (CSV)

One file per WAT month and currency (NGN for v1). Rows are `section, line, date,
reference, amount`.

1. Opening balance: our money at the end of the previous month, computed with the same
   definitions using an `as_of` timestamp.
2. Commission by source: framework sale, collection, project milestone, attestation fee.
3. Refunds reversed: commission removed by refunds this month.
4. Paystack fees.
5. Partner commissions.
6. Withdrawals: one row each with date, amount, reference and last 4.
7. Closing balance, which must equal opening + lines. A test asserts this.
8. Users' money at month end: held escrow, contributor balances, org balances, partner
   money.

- Uses the `as_of` variant of the summary queries, so the summary and the statement
  share one code path.
- Amounts are written as plain decimals with no currency symbol, so spreadsheets parse
  them.

## Frontend

- Route `/admin/treasury`, a client component, added to the admin nav.
- It follows the frontend-design skill (bento cards, mobile-first) and uses
  `useRefetchOnFocus`.
- **Cards:**
  - Available to withdraw (primary).
  - Our money, with an expandable breakdown.
  - Owed to users, with a breakdown.
  - Withdrawn (this month / all time).
  - Live Paystack balance, with "as of".
- **Warnings band:** balance gap, unreviewed unrecognized transfers, bank account on hold.
- **Withdraw dialog** (super-admin only; hidden for other admins, with read-only text):
  amount input with min/max hint, destination last 4, step-up prompt.
- **Bank account card:** change dialog, super-admin only, with step-up. Shows Paystack's
  resolved account name for confirmation before saving.
- **Withdrawals history:** card stack on mobile, table on `md:`.
- **Unrecognized transfers list:** with an acknowledge action.
- **Statements:** month picker and download. The download uses a generated SDK call that
  returns a blob, never a raw path.
- **Stripe section:** ledger lines, labelled "Not withdrawable here".

## Build slices (TDD, one at a time, human commits after each)

1. **Provider fees:** migration 0111, recording from `charge.success`. Tests: fee stored,
   webhook retry doesn't duplicate, refund keeps fee.
2. **Treasury summary:** service with an `as_of` option and `GET /summary`. Tests:
   aggregates match per-account balances; each liability and our-money line; withdrawable
   min rule; gap sign; balance fetch failure.
3. **Platform bank account:** 0112, `GET/PUT /bank-account`. Tests: super-admin only,
   step-up, 24h hold, replace keeps history, 502 stores nothing, audit + emails.
4. **Withdrawals:** 0113 + config, request endpoint, Celery task, transfer webhooks
   (success/failed/reversed, fee). Tests: every 4xx in §Withdrawal, one in flight
   (concurrent requests), task idempotent, failure returns amount, emails.
5. **Unrecognized transfers:** 0114, detection in the Paystack transfer branch, alert,
   list + acknowledge.
6. **Fee backfill:** `fetch_transaction`, task, endpoint.
7. **Statement CSV:** closing = opening + lines; WAT month boundaries.
8. **Contract + frontend:** openapi splice, SDK regen, `/admin/treasury` page, vitest,
   375px check. An e2e test for the withdrawal flow uses a mocked provider.

Backend endpoints land before the frontend. `contracts/openapi.yaml` is updated inside
each backend slice that adds an endpoint.

## Risks

- **Money integrity:** a wrong "owed to users" figure would let us withdraw user money.
  Mitigations:
  - Shared predicates plus the aggregate-equals-sum test.
  - The live-balance side of the min() rule.
  - The in-flight DB constraint and advisory lock.
- **Dashboard access still bypasses everything.** Detection is after the fact, so the
  human should also restrict Paystack dashboard users and enforce 2FA there.
- **Fee field uncertainty (open item A):** fees could be under-recorded until verified in
  Paystack test mode. The gap warning would surface the difference.
- **Staging:** withdrawals move real test-mode money in the shared Paystack test
  account. Harmless, but staging and local share one balance, so gap warnings there are
  expected.
- **No infra change:** the new Celery tasks run in the existing worker, so there is no
  terraform apply.

## Open items for the human

- **A.** Transfer fee source, to be verified in Paystack test mode during slice 4.
- **B.** Whether a Stripe-side unrecognized transfer detector is wanted later. It is out
  of v1.
