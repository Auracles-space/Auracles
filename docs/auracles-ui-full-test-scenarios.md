# Auracles — UI Test Scenarios & Inputs (v2)

What to test, what to enter, what to expect. Tester drives the UI; this doc supplies the **flows, the actors, the sample inputs/params, and the pass condition**. No click-by-click — you know the screens.

**Scope:** local stack first; same scenarios re-run on live after go-ahead. Payments in **test mode**, S3 = LocalStack, email captured (check logs/test inbox), ClamAV container running for scan paths.

**What's new in v2 vs v1:** Google sign-in, Organizations (core + attestor + contributor + operator capabilities), redefined Attestation (org-attestor pipeline: offers → rubric review → report → acceptance), Google Drive connectors (import, source binding, preview, re-sync, re-bind), artifact PII/similarity/rarity pipeline, framework reviews, project amendments + acceptance-cancel + milestone finalize/reopen, profiles with avatar/banner, notifications, org admin surfaces, expanded scheduled tasks.

---

## Test data bank (reuse across scenarios)

### Accounts (register these once)

Every account kind needed to cover every feature. **Setup state** = one-time prep to do right after registering, before its sections. **Covers** = the sections that need this exact account.

| Handle | Email | Password | Roles | Setup state | Covers |
|--------|-------|----------|-------|-------------|--------|
| Contributor | contrib@auracles.dev | Contrib-Pass-2026 | contributor | 2FA enrolled; KYC verified (via AD-3); Stripe Connect payout account; Google Drive connected (§6) | §2 profiles, §4 frameworks, §5 artifacts, §6 connectors, §9 payouts, §13 attestation requestor, §16 credentials, §17 reputation, §18 collections |
| Operator | operator@auracles.dev | Operator-Pass-2026 | operator | 2FA enrolled; Stripe payment method saved | §3 explore, §7 purchases, §8 reviews (RV-1/3), §10 projects (operator side), §18 saved searches, §20–21 |
| Operator 2 | operator2@auracles.dev | Operator2-Pass-26 | operator | none | negative cases: PU-7 no-license download, RV-2 review w/o license, PR-16 non-member workspace, PF-5 public-profile view, CR-4 unauthorized evidence |
| Dual | dual@auracles.dev | Dual-Pass-2026! | contributor + operator | 2FA enrolled | PU-11 self-deal block, §10 contributor side (proposals/deliverables), role-switch UX |
| NG Operator | ng.operator@auracles.dev | Naija-Pass-2026 | operator, country NG | Paystack payment method | PU-4 Paystack routing, NGN currency display |
| Developer | developer@auracles.dev | Developer-Pass-26 | operator | approved partner application (DV-2) | §19 developer platform (keys, webhooks, tier, partner payouts) |
| Org Owner | orgowner@auracles.dev | OrgOwner-Pass-26 | operator | 2FA enrolled (org payment method setup is TOTP-gated) | §11 org core (owner/admin actions), §12 attestor application, §14–15 capability activation, org checkout/funding |
| Org Member | orgmember@auracles.dev | OrgMember-Pass-26 | (none; joins via invitation) | none | OR-4/5 invitation accept, OO-5/6 grants + granted download, OR-12 member-RBAC 403s, OO-14 / GD-2 member exit |
| Org Member 2 | orgmember2@auracles.dev | OrgMember2-Pass2026 | (none; joins via invitation) | NDA signed in Acme Advisory (OA-1) | OR-8 teams, OA-4 trial nominee, OA-9/10 reviewing-member workspace, promoted admin for OR-6/OR-9 transfer target |
| Admin | from bootstrap_admin.py | (ADMIN_PASSWORD) | admin | 2FA enrolled (RE-5 recompute is TOTP-gated) | §22 all admin, AD-* references inside other sections |
| Google user | a real Google test account you control | (Google) | roleless at first login | none — stays passwordless until GA-6 | §1b Google auth, GA-7 passwordless re-auth, onboarding role step |

Throwaway accounts — register when the scenario needs them; each is consumed/mutated by its test:

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |

> Password policy = **≥ 12 chars**. Use a sub-12 value (`Short1`) to test rejection.
>
> **Email domains:** use `auracles.dev` (or any real TLD you control) — **not** `.test`, `.example`, `.invalid`, `.localhost`, or `example.com/.net/.org`. Those are RFC 2606 reserved/special-use names and `email-validator` rejects them at registration ("…special-use or reserved name that cannot be used with email"). No real inbox needed for the seeded accounts — email is captured in logs/test inbox per the Scope note. Individual attestors no longer exist — attestation is organization-based. The old "apply as attestor" user is gone. The **Google user** doing Drive-connector tests (§6) can be the same Google account — connector OAuth is per-user via Contributor's settings, independent of Google *login*.

### Setup order (dependencies between accounts)

1. Admin exists first (`bootstrap_admin.py`) — needed to verify KYC, approve org-attestor application, approve developer application.
2. Register Contributor, Operator, Operator 2, Dual, NG Operator, Developer, Org Owner, Org Member, Org Member 2 → verify emails.
3. Enroll 2FA where the table says so; save payment methods; Contributor: KYC (ST-4 → AD-3) + payout onboarding (FN-2) + Drive connect (CN-1).
4. Org Owner creates both orgs (§11); invites Org Member + Org Member 2 into both; promotes Org Member 2 to admin in `Acme Advisory`.
5. `Acme Advisory`: NDA signatures → attestor application → admin pipeline (OA-2..7). `Northwind Ops`: activate contributor + operator capabilities (OC-1, OO-1); org payment method (OO-2).
6. Developer applies (DV-1) → admin approves (DV-2).
7. Do OR-9 (transfer ownership) and OR-10 (delete org) **last** in §11 — they mutate org state other sections depend on; use the throwaway `Scratch Org` if running §12–15 afterwards.

### Organizations (create during Section 11)

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |

### Payment test cards

- **Stripe success:** `4242 4242 4242 4242`, any future expiry (`12/30`), CVC `123`, ZIP `42424`.
- **Stripe decline:** `4000 0000 0000 0002`.
- **Stripe 3DS/auth-required:** `4000 0025 0000 3155`.
- **Paystack success (NGN):** `4084 0840 8408 4081`, expiry `12/30`, CVV `408`, OTP `123456`, PIN `1234`.

### Files

- Valid artifact: small `.pdf` and `.docx` (< 5 MB).
- Wrong type: `.exe` or `.zip` → rejection (415/type error).
- Oversized: file above cap → 413/too-large.
- EICAR test string in a file → virus-scan rejection path.
- PII-bearing doc: a `.pdf`/`.docx` containing a fake SSN/email/phone block → PII review path.
- Logo/avatar: PNG/JPEG/WebP < 5 MB; also a `.svg` or > 5 MB PNG to test rejection.
- Google Drive: seed the connected Drive account with 2–3 small Docs/PDFs for connector import.

### TOTP

- Enroll with any authenticator (or `oathtool --totp -b <secret>`). Wrong code = `000000`.

---

## How to read each scenario

**As** = the account (from the bank above) performing the action; `A → B` means A acts first, B second; `—` means no login (public/anonymous) and `(beat)` means triggered by a scheduled task, not a user. **Inputs** = what to type/select. **Expect** = the pass condition. Test each at desktop **and** 375px mobile.

---

## 1. Auth & Identity

### 1a. Email/password

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| AU-1 | Register | — (new) | Contributor row data | Generic "if email is new, verification sent"; no account-exists leak. Verification email captured. |
| AU-2 | Password too short | — (new) | password Short1 | Submit disabled / 422 "≥12 chars". |
| AU-3 | Role combo | — (new: Dual) | roles = Contributor + Operator | Accepted (Attestor is no longer a self-serve individual role). |
| AU-4 | Verify email | Contributor; negative: Unverified | token from captured email | Email verified; login allowed. Unverified account can't log in; resend-verification works. |
| AU-5 | Login wrong pass | Operator | operator@auracles.dev / wrongpass1234 | 401 generic error. |
| AU-6 | Login OK | Operator | Operator row | Lands on role dashboard; refresh cookie set (HttpOnly); access token never in localStorage. |
| AU-7 | 2FA setup | Dual | enroll authenticator, enter current code | 2FA enabled; backup codes shown once; regenerate replaces them. |
| AU-8 | 2FA login | Dual | login then enter code at /2fa-challenge | Wrong 000000 → 401; valid code → in; backup code works once. |
| AU-9 | 2FA disable | Dual (re-enroll after) | valid TOTP required | Disabled; next login has no challenge. Re-enroll to restore bank state. |
| AU-10 | Forgot/reset | Suspend-me | email → reset link → new pass Reset-Pass-2026 | Old pass fails, new works. |
| AU-11 | Logout | Operator | — | Protected route redirects to /login; refresh token revoked (back button can't restore session). |
| AU-12 | Rate limit | — | 6+ rapid failed logins on operator@auracles.dev | Throttled response. |
| AU-13 | Route guard | — (logged out) | hit /dashboard/frameworks | Redirect to /login. |
| AU-14 | Token refresh | Operator | stay idle past 15 min, then act | Silent refresh; no logout, no error flash. |

### 1b. Google sign-in

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| GA-1 | New Google user | Google user | "Continue with Google" on /register, email NOT registered | Passwordless account created, email pre-verified (no verification mail), lands on onboarding role step. |
| GA-2 | Roleless onboarding | Google user | pick Contributor and/or Operator on onboarding step | Role saved via role assignment; role dashboard reachable. Gated actions before choosing → role-required block. |
| GA-3 | Auto-link | Google-link | "Continue with Google" with Google email = existing password account | Signs into the SAME account (one user, two login methods); no duplicate account. |
| GA-4 | 2FA honored | Google user (enroll TOTP first) | Google login on the TOTP-enabled account | TOTP challenge before session issued; wrong code → 401. |
| GA-5 | Bad state | — | tamper state param on callback (or replay old callback URL) | 400; no session. |
| GA-6 | Set a password | Google user | forgot-password flow → set Google-Pass-2026 | Both login methods now work. |
| GA-7 | Passwordless re-auth | Google user (before GA-6) | change email / request account deletion | NOT blocked on password: steps up via TOTP if enrolled, else email-confirmation path. Settings UI shows substitute factor, not a password field. |

## 2. Profiles

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| PF-1 | My profile | Contributor | open /profile/me | Own profile renders (display name, bio, roles, reputation, credentials). |
| PF-2 | Edit profile | Contributor | /profile/edit: display name Test Contributor, bio text | Saved; reflected on public profile. |
| PF-3 | Avatar upload | Contributor | PNG < 5 MB via upload → confirm | Two-step (presigned PUT + confirm); avatar renders. .svg or > 5 MB → rejected. |
| PF-4 | Banner upload | Contributor | JPEG < 5 MB | Same two-step; banner renders. |
| PF-5 | Public profile | Operator 2 | open Contributor's /profile/[id] | Public fields only — no email, no KYC status, no payout data anywhere in page or network tab. |

## 3. Explore / Discovery

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| EX-1 | Explore feed | — (logged out) | open /explore | Cards load fast; SSR (view-source contains content). |
| EX-2 | Search | — | query growth (or a published title keyword) | Relevant results; empty query handled. |
| EX-3 | Filters + paginate | — | category/price filter, next page | Correct subset; pagination stable. |
| EX-4 | Framework detail | — | open a published framework | Metadata, preview, price, attestation badges, reviews, reputation label, related frameworks. |
| EX-5 | Contributor profile | — | /explore → contributor link | Profile + reputation + verified credentials. |
| EX-6 | Org-owned framework | — | view a framework contributed by Northwind Ops (after §14) | Seller shown as the organization (name/logo), not the acting member. |
| EX-7 | Collections | — | /explore/collections + detail | Items + bundle price. |
| EX-8 | Attestor directory | — | /attestors public page | Approved attestor orgs listed; /attestors/[orgId] shows org profile + completed attestations. |
| EX-9 | Public org page | — | /orgs/acme-advisory | Public org profile by slug; no member emails/PII. |

## 4. Frameworks (Contributor)

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| FW-1 | Create draft | Contributor | title Series A Fundraising Playbook, desc, category, price 49.00 | Draft saved, listed in dashboard. |
| FW-2 | Price invalid | Contributor | price 0 or empty | Rejected (> 0 required). |
| FW-3 | Submit for review → publish | Contributor | submit draft (needs ≥1 processed artifact) | Can't publish until review passes; published shows in Explore. |
| FW-4 | Versioning | Contributor | create new version on published framework | New version; old retained; artifact source binding carried forward (see CN-8). |
| FW-5 | Unpublish + relist | Contributor | unpublish, then relist | Gone from Explore then back; existing licenses keep access throughout. |
| FW-6 | Delete draft | Contributor | delete an unpublished draft | Removed; published frameworks not deletable this way. |
| FW-7 | Non-owner edit | Operator 2 | edit Contributor's framework via URL | 403. |
| FW-8 | Preview artifact | Contributor | pick which artifact is the public preview | Detail page preview switches. |
| FW-9 | Analytics | Contributor; negative: Operator 2 | /dashboard/frameworks/[id]/analytics | Views/purchases render for owner; non-owner 403. |

## 5. Artifacts & processing pipeline

Upload = presigned PUT + confirm; then the `process_artifact` chain (virus scan → extract → PII → fingerprint → rarity → thumbnail → index). Status polls in the UI. **Actor throughout: Contributor** (owner of the draft), except where noted.

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| AR-1 | Upload valid | Contributor | small .pdf | Status walks to processed; thumbnail appears. |
| AR-2 | Wrong type | Contributor | .exe | Rejected (type error) — before S3 hit. |
| AR-3 | Oversized | Contributor | file > cap | 413/too-large — before S3 hit. |
| AR-4 | Virus | Contributor | EICAR file | Rejected with virus_detected; artifact unusable; ERROR logged. |
| AR-5 | PII detected | Contributor | PII-bearing doc | Pipeline flags PII; owner sees review state. |
| AR-6 | PII resolve | Contributor | resolve PII review (keep / redact) | Accept-redaction path produces redacted copy; framework can proceed. |
| AR-7 | Soft-fail ack | Contributor | artifact with a soft processing failure | Owner must acknowledge before submit proceeds. |
| AR-8 | Similarity notice | Contributor | upload artifact near-duplicating an existing one | Similarity notice shown; owner acknowledges to continue. |
| AR-9 | Rarity block | Contributor → Admin | upload highly-duplicative content | Publish blocked on rarity; admin override (AD-8) unblocks. |
| AR-10 | Delete artifact | Contributor | remove an artifact from a draft | Gone from list; S3 object cleaned up (orphan sweep tolerates it). |
| AR-11 | Stalled processing | Contributor + tester | kill worker mid-scan, wait for reaper (SC-17) or run it | Artifact fails cleanly, not stuck "processing" forever; re-upload works. |

## 6. Connectors (Google Drive)

**Actor throughout: Contributor** (Drive connected in setup), except CN-10.

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| CN-1 | Connect | Contributor | /settings/integrations → Connect Google Drive → OAuth consent | Connection listed as active. |
| CN-2 | Browse + import | Contributor | in framework editor: "Import from Drive", pick 2 files | Both copied in as artifacts, processed like uploads; source binding stamped (Drive badge on artifact). |
| CN-3 | Draft source preview | Contributor | view draft artifact imported from Drive | Live Drive thumbnail renders (proxied/cached — network tab shows OUR host, never a raw googleusercontent token URL). |
| CN-4 | Preview gating | Operator (licensed) + — | view same artifact after publish / as non-owner | No live preview — static/processed preview only. |
| CN-5 | Re-sync | Contributor | edit the file in Drive, click Re-sync on draft artifact | New copy pulled; byte change → new immutable artifact version (copy-on-write), old bytes retained for sold copies. |
| CN-6 | Re-bind | Contributor | attach a source to an unbound artifact / repoint to a different Drive file | Binding updates; next re-sync pulls from new source. |
| CN-7 | Detach | Contributor | detach source from artifact | Binding cleared; re-sync unavailable; artifact bytes untouched. |
| CN-8 | Version carry | Contributor | bump framework version (FW-4) | Source bindings carried to new version's artifacts. |
| CN-9 | Disconnect | Contributor | disconnect Drive in settings | Connection revoked; bound artifacts keep bytes, re-sync now fails gracefully (no crash/500). |
| CN-10 | GDPR revoke | Delete-me | run account deletion (GD-2) with a Drive connection | oauth connection revoked + purged. |

## 7. Purchase + Library (individual Operator)

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |0

## 8. Framework reviews

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |1

## 9. Financials / Payouts (individual)

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |2

## 10. Projects + Workspace (individual)

Operator posts + funds; **Dual** is the bidding Contributor side.

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |3

## 11. Organizations — Core

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |4

## 12. Organizations — Attestor capability (`Acme Advisory`)

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |5

## 13. Attestation (requestor side)

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |6

## 14. Organizations — Contributor capability (`Northwind Ops`)

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |7

## 15. Organizations — Operator capability (`Northwind Ops`)

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |8

## 15b. Organizations — Team-scoped capability rights (`Northwind Ops`)

**Model under test.** Activating a capability (OC-1/OO-1) only makes the org *eligible*. The derived role (Contributor / Operator / Attestor) is held by an **owner/admin automatically**, and by a **plain member only through a team** that has the capability enabled. Leaving that team (or disabling the capability on it) revokes the role. UI: org → **Profile** tab → **Capabilities** card (activate); org → **Teams** → per-team capability toggles + confirm dialog; expand a team to add/remove members.

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | unverified@auracles.dev | Unverified-Pass26 | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | suspendme@auracles.dev | SuspendMe-Pass-26 | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | deleteme@auracles.dev | DeleteMe-Pass-2026 | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register your.gmail@gmail.com with a password first, then "Continue with Google"). |9

> Authoritative role check (if UI is ambiguous): the derived grant is a `user_roles` row with `source='derived'` for that user and role (`contributor` / `operator` / `attestor`). Present ⇒ granted; absent ⇒ not.

## 16. Credentials

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |0

## 17. Reputation

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |1

## 18. Collections & Saved searches

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |2

## 19. Developer platform

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |3

## 20. Notifications

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |4

## 21. Settings

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |5

## 22. Admin

**Actor: Admin** throughout; targets named per row.

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |6

## 23. GDPR

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |7

## 24. Scheduled / automatic tasks (Celery Beat)

Actor = tester/ops (no UI account) — you trigger the task, then verify effect as the account named in the referenced scenario.

**How to trigger without waiting:**

- Start scheduler + worker: `make beat` **plus** `make worker`.
- Or force-run one task now: `cd backend && uv run python -c "from app.workers.tasks.<module> import <task>; <task>.apply()"`.
- For expiry/overdue cases, set the relevant timestamp into the past in the DB, or lower the window in `platform_config`, then run the task. **Re-run once more to confirm idempotency** (no double effect).

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |8

---

## Cross-cutting checks (apply while testing above)

- **RBAC:** every gated screen — logged out → login redirect; wrong role → 403/blocked; wrong **org role** (member vs admin vs owner) → tab hidden AND endpoint 403 (check both).
- **Acting-identity clarity:** anywhere a user can act as self OR as an org (checkout, projects, reviews), the UI states which identity is acting, and the backend attributes to that identity — verify in DB/response, not just UI.
- **Mobile 375px:** no horizontal scroll on tables (card-stack), tap targets ≥ 44px, modals full-screen, org tab bar usable.
- **Errors:** bad input → clear 422; not-found → 404; duplicate submit → no 500 (replay purchase, double-click fund/approve buttons); external failure → graceful message.
- **Security eyeballs:** downloads always presigned (never proxied file bytes from API, except the connector preview proxy which must never expose Google tokens); no secrets/tokens in network tab or logs; PII absent from list endpoints; reviewing-member and grant provenance fields absent from responses.
- **Money atomicity:** kill/refresh mid-checkout and mid-fund — no half-states (charged without license, funded without escrow row).
- **Empty/loading states:** skeletons + empty states render, not blank/spinners-forever — especially new org tabs with no data.
- **Status page:** `/status` renders foundation status.

---

## Release-blocking flows (must all pass before live go-ahead)

| Name | Slug | Purpose |
|------|------|---------|
| Acme Advisory | acme-advisory | Attestor-capability org |
| Northwind Ops | northwind-ops | Operator + Contributor capability org |
| Scratch Org | scratch-org | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |9

---

## Sign-off — live go-ahead gate

Live testing is authorized **only** when every row is green.

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| AU-1 | Register | — (new) | Contributor row data | Generic "if email is new, verification sent"; no account-exists leak. Verification email captured. |
| AU-2 | Password too short | — (new) | password Short1 | Submit disabled / 422 "≥12 chars". |
| AU-3 | Role combo | — (new: Dual) | roles = Contributor + Operator | Accepted (Attestor is no longer a self-serve individual role). |
| AU-4 | Verify email | Contributor; negative: Unverified | token from captured email | Email verified; login allowed. Unverified account can't log in; resend-verification works. |
| AU-5 | Login wrong pass | Operator | operator@auracles.dev / wrongpass1234 | 401 generic error. |
| AU-6 | Login OK | Operator | Operator row | Lands on role dashboard; refresh cookie set (HttpOnly); access token never in localStorage. |
| AU-7 | 2FA setup | Dual | enroll authenticator, enter current code | 2FA enabled; backup codes shown once; regenerate replaces them. |
| AU-8 | 2FA login | Dual | login then enter code at /2fa-challenge | Wrong 000000 → 401; valid code → in; backup code works once. |
| AU-9 | 2FA disable | Dual (re-enroll after) | valid TOTP required | Disabled; next login has no challenge. Re-enroll to restore bank state. |
| AU-10 | Forgot/reset | Suspend-me | email → reset link → new pass Reset-Pass-2026 | Old pass fails, new works. |
| AU-11 | Logout | Operator | — | Protected route redirects to /login; refresh token revoked (back button can't restore session). |
| AU-12 | Rate limit | — | 6+ rapid failed logins on operator@auracles.dev | Throttled response. |
| AU-13 | Route guard | — (logged out) | hit /dashboard/frameworks | Redirect to /login. |
| AU-14 | Token refresh | Operator | stay idle past 15 min, then act | Silent refresh; no logout, no error flash. |0

**Live go-ahead granted by William:** ☐ — date: ________

### Defect log

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| AU-1 | Register | — (new) | Contributor row data | Generic "if email is new, verification sent"; no account-exists leak. Verification email captured. |
| AU-2 | Password too short | — (new) | password Short1 | Submit disabled / 422 "≥12 chars". |
| AU-3 | Role combo | — (new: Dual) | roles = Contributor + Operator | Accepted (Attestor is no longer a self-serve individual role). |
| AU-4 | Verify email | Contributor; negative: Unverified | token from captured email | Email verified; login allowed. Unverified account can't log in; resend-verification works. |
| AU-5 | Login wrong pass | Operator | operator@auracles.dev / wrongpass1234 | 401 generic error. |
| AU-6 | Login OK | Operator | Operator row | Lands on role dashboard; refresh cookie set (HttpOnly); access token never in localStorage. |
| AU-7 | 2FA setup | Dual | enroll authenticator, enter current code | 2FA enabled; backup codes shown once; regenerate replaces them. |
| AU-8 | 2FA login | Dual | login then enter code at /2fa-challenge | Wrong 000000 → 401; valid code → in; backup code works once. |
| AU-9 | 2FA disable | Dual (re-enroll after) | valid TOTP required | Disabled; next login has no challenge. Re-enroll to restore bank state. |
| AU-10 | Forgot/reset | Suspend-me | email → reset link → new pass Reset-Pass-2026 | Old pass fails, new works. |
| AU-11 | Logout | Operator | — | Protected route redirects to /login; refresh token revoked (back button can't restore session). |
| AU-12 | Rate limit | — | 6+ rapid failed logins on operator@auracles.dev | Throttled response. |
| AU-13 | Route guard | — (logged out) | hit /dashboard/frameworks | Redirect to /login. |
| AU-14 | Token refresh | Operator | stay idle past 15 min, then act | Silent refresh; no logout, no error flash. |1

---

## Live (post-go-ahead) — re-verify only the delta

After local sign-off, on live re-check only what differs from local — don't re-run the full matrix blind:

- Real env vars set on Render (all `sync:false` secrets) + Vercel, including Google OAuth client (login) AND Drive connector client.
- `drive.readonly` scope verification status — until Google approves, Drive connector limited to test users.
- `REDIS_URL` is `rediss://` Upstash base; app uses **DB 0 only**.
- Public health green: `https://<api>.onrender.com/v1/health` (no `:10000`).
- CORS allowlist = real Vercel origin (no `*`).
- Stripe/Paystack **live** webhooks registered + signing secrets set; replay-idempotency spot-check.
- S3 real buckets + least-privilege IAM; presigned URLs work; orphan-sweep age guard confirmed against real bucket before first beat run.
- ClamAV present in worker image (scan actually runs, not skipped).
- CI-gated deploy: Checks green → `deploy.yml` fires Render hooks.
- e2e `org-operator.spec.ts` passes in staging (pre-release gate).
- Smoke the 8 critical flows on live with test data before announcing to team.