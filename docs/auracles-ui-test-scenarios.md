# Auracles — UI Test Scenarios & Inputs

What to test, what to enter, what to expect. Tester drives the UI; this doc supplies the **flows, the sample inputs/params, and the pass condition**. No click-by-click — you know the screens.

**Scope:** local stack first; same scenarios re-run on live after go-ahead. Payments in **test mode**, S3 = LocalStack, email captured (check logs/test inbox).

---

## Test data bank (reuse across scenarios)

### Accounts (register these once)
| Handle | Email | Password | Roles |
|--------|-------|----------|-------|
| Contributor | `contrib@auracles.test` | `Contrib-Pass-2026` | contributor |
| Operator | `operator@auracles.test` | `Operator-Pass-2026` | operator |
| Dual | `dual@auracles.test` | `Dual-Pass-2026!` | contributor + operator |
| Attestor | `attestor@auracles.test` | `Attestor-Pass-26` | attestor (needs admin approval) |
| NG Operator | `ng.operator@auracles.test` | `Naija-Pass-2026` | operator, country **NG** |
| Admin | from `bootstrap_admin.py` | (`ADMIN_PASSWORD`) | admin |

> Password policy = **≥ 12 chars**. All above satisfy it. Use a sub-12 value (`Short1`) to test rejection.

### Payment test cards
- **Stripe success:** `4242 4242 4242 4242`, any future expiry (`12/30`), CVC `123`, ZIP `42424`.
- **Stripe decline:** `4000 0000 0000 0002`.
- **Stripe 3DS/auth-required:** `4000 0025 0000 3155`.
- **Paystack success (NGN):** `4084 0840 8408 4081`, expiry `12/30`, CVV `408`, OTP `123456`, PIN `1234`.

### Files for artifact upload
- Valid: a small `.pdf` and a `.docx` (< 5 MB).
- Wrong type: a `.exe` or `.zip` → expect rejection (415/type error).
- Oversized: a file above the cap → expect 413/too-large error.
- (EICAR test string in a file to exercise virus-scan path, if AV wired locally.)

### TOTP
- Enroll with any authenticator (or `oathtool --totp -b <secret>`). Wrong code = `000000`.

---

## How to read each scenario
**Inputs** = what to type/select. **Expect** = the pass condition. Test each at desktop **and** 375px mobile.

---

## 1. Auth & Identity

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| AU-1 | Register | Contributor row data | Generic "if email is new, verification sent"; no account-exists leak. Verification email captured. |
| AU-2 | Password too short | password `Short1` | Submit disabled / 422 "≥12 chars". |
| AU-3 | Role rule — invalid | roles = Attestor **+** Operator | Rejected: "Attestor cannot be combined with other roles." |
| AU-4 | Role rule — valid combo | roles = Contributor + Operator | Accepted. |
| AU-5 | Verify email | token from captured email | Email verified; login allowed. |
| AU-6 | Login wrong pass | `operator@auracles.test` / `wrongpass1234` | 401 generic error. |
| AU-7 | Login OK | Operator row | Lands on role dashboard; refresh cookie set (HttpOnly). |
| AU-8 | 2FA setup | enroll authenticator, enter current code | 2FA enabled; backup codes shown once. |
| AU-9 | 2FA login | login then enter code | Wrong `000000` → 401; valid code → in. |
| AU-10 | Forgot/reset | email → reset link → new pass `Reset-Pass-2026` | Old pass fails, new works. |
| AU-11 | Logout | — | Protected route redirects to `/login`. |
| AU-12 | Rate limit | 6+ rapid failed logins | Throttled response. |
| AU-13 | Route guard | hit `/dashboard/frameworks` logged out | Redirect to `/login`. |

## 2. Explore / Discovery

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| EX-1 | Explore feed | open `/explore` | Cards load, fast. |
| EX-2 | Search | query `growth` (or a published title keyword) | Relevant results; empty query handled. |
| EX-3 | Filters + paginate | pick a category/price filter, next page | Correct subset; pagination stable. |
| EX-4 | Framework detail | open a published framework | Metadata, preview, price, attestations, reputation badge. |
| EX-5 | Contributor profile | `/explore/contributors/[id]` | Profile + reputation + verified credentials. |
| EX-6 | Collection page | `/explore/collections/[id]` | Items + bundle price. |

## 3. Frameworks (Contributor)

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| FW-1 | Create draft | title `Series A Fundraising Playbook`, desc (≥ some chars), category, price `49.00` | Draft saved, listed in dashboard. |
| FW-2 | Price invalid | price `0` or empty | Submit disabled / rejected (>0 required). |
| FW-3 | Upload artifact | valid `.pdf` | Upload OK; processing status shows then completes. |
| FW-4 | Wrong file type | `.exe` | Rejected (type error). |
| FW-5 | Oversized file | file > cap | 413/too-large. |
| FW-6 | Submit for review → publish | submit draft | Can't publish until reviewed (BR-FWK-007); published shows in Explore. |
| FW-7 | Versioning | edit + new version | New version; old retained. |
| FW-8 | Unpublish | unpublish published fw | Gone from Explore; existing licenses keep access. |
| FW-9 | Non-owner edit | login as other user, edit URL | 403. |

## 4. Purchase + Library (Operator)

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| PU-1 | Purchase (Stripe) | Stripe success card | License created; confirmation; appears in `/library`. |
| PU-2 | Card declined | `4000 0000 0000 0002` | Decline surfaced; no license. |
| PU-3 | 3DS card | `4000 0025 0000 3155` | Auth challenge handled. |
| PU-4 | NG routing | login NG Operator, purchase | Routed to **Paystack**, NGN. Use Paystack test card. |
| PU-5 | Download artifact | open purchased fw → download | Presigned URL (expires ~15m); logged. |
| PU-6 | Download w/o license | other user hits download | 403, no URL. |
| PU-7 | Collection checkout | buy a collection | Bundle license created. |

## 5. Financials / Payouts (Contributor)

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| FN-1 | Connect onboarding | start Stripe Connect / Paystack onboarding | Account link completes. |
| FN-2 | Earnings | open earnings | Totals + history correct. |
| FN-3 | Payout no KYC | request payout, KYC not verified | Blocked. |
| FN-4 | Payout no 2FA | KYC ok, omit 2FA code | Blocked; with valid TOTP → accepted. |
| FN-5 | Payout amount | amount `100.00`, valid account, TOTP | Accepted; amount > balance → rejected. |
| FN-6 | Refund | trigger refund path | Refund issued; balances consistent. |

## 6. Projects + Workspace

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| PR-1 | Post project (Operator) | title `Migrate billing to Stripe`, desc, category, budget min `500` / max `2000`, deliverable fields | Posted; min<max enforced; budgets > 0. |
| PR-2 | Proposal (Contributor) | scope text, bid `1500` | Bid recorded. |
| PR-3 | Accept proposal | accept | Workspace created; membership set. |
| PR-4 | Fund milestone | milestone name, amount `1500` | Escrow funded. |
| PR-5 | Submit deliverable | upload file + note | Operator notified. |
| PR-6 | Approve deliverable | approve | Escrow released to contributor. |
| PR-7 | Auto-release | let approval window lapse, no dispute | Escrow auto-releases (only automatic release). |
| PR-8 | Dispute | raise dispute before approval | Escrow held; auto-release blocked. |
| PR-9 | Resolve dispute | admin/agreed resolution | Funds move per outcome; reputation effect (fault-aware). |
| PR-10 | Realtime | two browsers in workspace | Activity updates live. |
| PR-11 | Non-member | stranger opens workspace URL | 403/404. |

## 7. Attestation

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| AT-1 | Apply as attestor | application + evidence | Pending admin approval. |
| AT-2 | Admin approve attestor | admin approves | Role approved; assignable. |
| AT-3 | Request attestation | request on a framework | Fee escrowed. |
| AT-4 | Assignment | login attestor | Shows in `/attestor/assignments`. |
| AT-5 | Submit report | score + findings | PDF generated; status updates. |
| AT-6 | Publish report | publish | Visible on framework detail; reputation updates. |
| AT-7 | Reject report | reject path | Adverse → fault-aware penalty. |

## 8. Credentials (verification)

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| CR-1 | Add credential | issuer, type, title, evidence file | Stored; status pending. |
| CR-2 | Admin queue | open `/admin/credentials` | Pending listed. |
| CR-3 | View evidence | admin opens evidence | Presigned GET (admin/owner only); audited. |
| CR-4 | Verify/reject | admin verifies | Verified badge on public profile. |
| CR-5 | Unauthorized evidence | non-admin/non-owner | 403. |

## 9. Reputation

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| RE-1 | New framework | freshly published fw | "New"/provisional label. |
| RE-2 | Accrue signals | add reviews + approved attestation, recompute | Score appears, strong factor labels. |
| RE-3 | Penalty | dispute resolved against contributor | Score drops, decays over time. |
| RE-4 | Operator visibility | view operator rep | Visible to in-deal contributor/self/admin; absent in public Explore. |
| RE-5 | Anti-gaming | inspect surface | Labels only; no raw weights. |
| RE-6 | Manual recompute | admin + TOTP | Single-subject recompute; idempotent. |

## 10. Collections & Saved Searches

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| CS-1 | Create collection | name `Fundraising Pack`, add frameworks | Listed in dashboard. |
| CS-2 | Save search | run search, save name `Growth tools` | Stored in settings. |
| CS-3 | Saved-search alert | new matching framework published | Alert email (Beat) fires. |

## 11. Developer Platform

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| DV-1 | Apply | company `Acme`, use-case text, website `https://acme.dev` | Recorded; invalid URL `acme` rejected. |
| DV-2 | API key | label `prod-key` | Key shown once. |
| DV-3 | Partner call | call partner API with key | OK; bad key → 401. |
| DV-4 | Webhook | url `https://acme.dev/hooks`, select events | Saved. |
| DV-5 | Delivery + retry | trigger event | Delivered; failure retried. |
| DV-6 | Usage/commissions | open dashboard | Accurate. |

## 12. Settings

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| ST-1 | Profile | edit display name/bio | Saved. |
| ST-2 | Email change | new email + TOTP | 2FA required; verification sent. |
| ST-3 | Payment method | change + TOTP | 2FA required. |
| ST-4 | Payout accounts | add bank/Stripe acct | Added; KYC-gated for payout. |
| ST-5 | KYC upload | ID document file | Status pending. |
| ST-6 | Notifications | toggle types | Persist; respected by delivery. |
| ST-7 | Sessions | view + revoke a session | Revoked session logged out. |
| ST-8 | Consent/onboarding | complete steps | Flows finish. |

## 13. Admin

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| AD-1 | Users / suspend | suspend a user | Suspended can't log in; audited. |
| AD-2 | Moderation | flag/remove content | Works. |
| AD-3 | Analytics | open analytics | Metrics render. |
| AD-4 | Config | set reputation weights | Sum≈1 enforced; bad config 422. |
| AD-5 | RBAC | non-admin hits `/admin/*` | 403 + WARNING log. |

## 14. GDPR

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| GD-1 | Export | request data export | Job runs; download link delivered. |
| GD-2 | Delete | request deletion | Data removed/anonymized. |
| GD-3 | Consent | view consent records | Retrievable. |

## 15. Scheduled / Automatic tasks (Celery Beat)

These fire on a timer, not on a click. Some are covered by feature rows above
(PR-7 deliverable auto-release, RE-2/RE-6 reputation recompute, CS-3 saved-search
alert) — the rows below cover the rest.

**How to trigger without waiting:**
- Start the scheduler: `make beat` **plus** `make worker` (beat enqueues, the worker runs).
- Or force-run a single task now (worker not required):
  `cd backend && uv run python -c "from app.workers.tasks.<module> import <task>; <task>()"`
  (e.g. `from app.workers.tasks.projects_beat import auto_approve_deliverables; auto_approve_deliverables()`).
- For "expiry"/"overdue" cases, set the relevant timestamp into the past in the DB
  (e.g. `created_at`, `expires_at`, `deadline_at`) — or lower the window in
  `platform_config` — then run the task. Re-run once more to confirm **idempotency**
  (no double effect).

| # | Flow | Inputs | Expect |
|---|------|--------|--------|
| SC-1 | Attestation auto-release | assignment past its release window, no dispute (`attestation_beat.auto_release_attestations`) | Attestation fee escrow releases to attestor; audited. |
| SC-2 | Attestation offer expiry | unaccepted offer past expiry (`attestation_beat.expire_attestation_offers`) | Offer expired; no longer assignable. |
| SC-3 | Overdue attestation revoke | assigned attestor misses deadline (`attestation_beat.revoke_overdue_attestations`) | Assignment revoked/reassignable; attestor notified. |
| SC-4 | Attestation dispute escalation | attestation dispute past SLA (`attestation_beat.escalate_attestation_disputes`) | Escalated to admin queue. |
| SC-5 | Open proposal expiry | proposal open past window (`projects_beat.expire_open_proposals`) | Proposal expired; can't be accepted. |
| SC-6 | Pending amendment expiry | milestone/contract amendment unactioned past window (`projects_beat.expire_pending_amendments`) | Amendment expired; state reverts. |
| SC-7 | Project dispute escalation | project dispute past SLA (`projects_beat.escalate_disputes`) | Escalated to admin; escrow stays held. |
| SC-8 | Close expired project | posted project past deadline, no acceptance (`projects_beat.close_expired_projects`) | Project closed; no longer biddable. |
| SC-9 | Auto-close delivered project | all milestones delivered/approved (`projects_beat.auto_close_delivered_projects`) | Project auto-closes; final state set. |
| SC-10 | License expiry | license past `expires_at` (`scheduled.clear_expired_licenses`) | Access revoked; download blocked. |
| SC-11 | GDPR export expiry | export past TTL (`gdpr_beat.expire_data_exports`) | File purged; download link dead (410). |
| SC-12 | Account deletion processing | deletion request past grace period (`gdpr_beat.process_account_deletions`) | Account anonymized/removed; audited. |
| SC-13 | Partner webhook retry | a delivery left failed (`partner_webhooks.retry_due_partner_webhooks`) | Re-attempted on schedule; succeeds or marks exhausted. |
| SC-14 | Partner commission clear | commission window elapses (`developer_beat.clear_partner_commissions`) | Commissions settled/cleared for the period. |
| SC-15 | Partner tier recompute | partner usage changes (`developer_beat.recompute_partner_tiers`) | Tier recomputed from usage; reflected in dashboard. |
| SC-16 | Daily analytics snapshot | run daily job (`admin_beat.snapshot_daily_analytics`) | Snapshot row written; admin analytics reflect it. |

---

## Cross-cutting checks (apply while testing above)

- **RBAC:** every gated screen — logged out → login redirect; wrong role → 403/blocked.
- **Mobile 375px:** no horizontal scroll on tables (card-stack), tap targets ≥ 44px, modals full-screen.
- **Errors:** bad input → clear 422 message; not-found → 404; duplicate submit → no 500; external failure → graceful message.
- **Security eyeballs:** downloads always presigned (never a proxied file URL); no secrets/tokens visible in network tab or logs; PII not shown in list screens.
- **Empty/loading states:** skeletons + empty states render, not blank/spinners-forever.

---

## Six release-blocking flows (must all pass before live go-ahead)

1. Register → verify email → role selected.
2. Contributor: create framework → upload artifact → submit → published.
3. Operator: search → purchase → download.
4. Operator: create project → contributor bids → accepted → milestone funded → deliverable approved → escrow released.
5. Attestation: request → assigned → report submitted → published.
6. Contributor: payout request with 2FA.

---

## Sign-off — live go-ahead gate

Live testing is authorized **only** when every row is green.

| Area | Description | Status | Signed | Date |
|------|-------------|--------|--------|------|
| Sections 1–15 | All feature scenarios pass (desktop + 375px) | ☐ | | |
| Cross-cutting | RBAC, mobile, errors, security eyeballs, empty/loading | ☐ | | |
| Critical flows | All 6 release-blocking flows pass | ☐ | | |
| Defects | No open Critical/High defects | ☐ | | |

**Live go-ahead granted by William:** ☐ — date: ________

### Defect log

| ID | Scenario | Severity | Description | Status |
|----|----------|----------|-------------|--------|
| | | | | |

---

## Live (post-go-ahead) — re-verify only the delta

After local sign-off, on live re-check only what differs from local — don't re-run the full matrix blind:

- [ ] Real env vars set on Render (all `sync:false` secrets) + Vercel.
- [ ] `REDIS_URL` is `rediss://` Upstash base; app uses **DB 0 only** (`dep-steps.md` §2 says "/0 and /1" — stale, correct it).
- [ ] Public health green: `https://<api>.onrender.com/v1/health` (no `:10000`).
- [ ] CORS allowlist = real Vercel origin (no `*`).
- [ ] Stripe/Paystack **live** webhooks registered + signing secrets set.
- [ ] S3 real buckets + least-privilege IAM; presigned URLs work.
- [ ] CI-gated deploy: Checks green → `deploy.yml` fires Render hooks.
- [ ] Smoke the 6 critical flows on live with test data before announcing to team.
