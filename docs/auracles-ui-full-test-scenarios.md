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
| Contributor | `contrib@auracles.dev` | `Contrib-Pass-2026` | contributor | 2FA enrolled; KYC verified (via AD-3); Stripe Connect payout account; Google Drive connected (§6) | §2 profiles, §4 frameworks, §5 artifacts, §6 connectors, §9 payouts, §13 attestation requestor, §16 credentials, §17 reputation, §18 collections |
| Operator | `operator@auracles.dev` | `Operator-Pass-2026` | operator | 2FA enrolled; Stripe payment method saved | §3 explore, §7 purchases, §8 reviews (RV-1/3), §10 projects (operator side), §18 saved searches, §20–21 |
| Operator 2 | `operator2@auracles.dev` | `Operator2-Pass-26` | operator | none | negative cases: PU-7 no-license download, RV-2 review w/o license, PR-16 non-member workspace, PF-5 public-profile view, CR-4 unauthorized evidence |
| Dual | `dual@auracles.dev` | `Dual-Pass-2026!` | contributor + operator | 2FA enrolled | PU-11 self-deal block, §10 contributor side (proposals/deliverables), role-switch UX |
| NG Operator | `ng.operator@auracles.dev` | `Naija-Pass-2026` | operator, country **NG** | Paystack payment method | PU-4 Paystack routing, NGN currency display |
| Developer | `developer@auracles.dev` | `Developer-Pass-26` | operator | approved partner application (DV-2) | §19 developer platform (keys, webhooks, tier, partner payouts) |
| Org Owner | `orgowner@auracles.dev` | `OrgOwner-Pass-26` | operator | 2FA enrolled (org payment method setup is TOTP-gated) | §11 org core (owner/admin actions), §12 attestor application, §14–15 capability activation, org checkout/funding |
| Org Member | `orgmember@auracles.dev` | `OrgMember-Pass-26` | (none; joins via invitation) | none | OR-4/5 invitation accept, OO-5/6 grants + granted download, OR-12 member-RBAC 403s, OO-14 / GD-2 member exit |
| Org Member 2 | `orgmember2@auracles.dev` | `OrgMember2-Pass2026` | (none; joins via invitation) | NDA signed in `Acme Advisory` (OA-1) | OR-8 teams, OA-4 trial nominee, OA-9/10 reviewing-member workspace, promoted admin for OR-6/OR-9 transfer target |
| Admin | from `bootstrap_admin.py` | (`ADMIN_PASSWORD`) | admin | 2FA enrolled (RE-5 recompute is TOTP-gated) | §22 all admin, AD-* references inside other sections |
| Google user | a real Google test account you control | (Google) | roleless at first login | none — stays passwordless until GA-6 | §1b Google auth, GA-7 passwordless re-auth, onboarding role step |

Throwaway accounts — register when the scenario needs them; each is consumed/mutated by its test:

| Handle | Email | Password | Consumed by |
|--------|-------|----------|-------------|
| Unverified | `unverified@auracles.dev` | `Unverified-Pass26` | AU-4 negative: registered but never verified → login blocked until verify; resend-verification. |
| Suspend-me | `suspendme@auracles.dev` | `SuspendMe-Pass-26` | AD-1 suspend/unsuspend (reversible, reusable after); AU-10 forgot/reset (its password may drift — fine, throwaway). |
| Delete-me | `deleteme@auracles.dev` | `DeleteMe-Pass-2026` | GD-2 account deletion (destroyed — register fresh per run). Give it: one org membership with a grant (OO-14), a Drive connection (CN-10) before deleting. |
| Google-link | existing email/password account re-registered with matching Google email | — | GA-3 auto-link (needs a Google account whose email equals an existing password account — easiest: register `your.gmail@gmail.com` with a password first, then "Continue with Google"). |

> Password policy = **≥ 12 chars**. Use a sub-12 value (`Short1`) to test rejection.
>
> **Email domains:** use `auracles.dev` (or any real TLD you control) — **not** `.test`, `.example`, `.invalid`, `.localhost`, or `example.com/.net/.org`. Those are RFC 2606 reserved/special-use names and `email-validator` rejects them at registration ("…special-use or reserved name that cannot be used with email"). No real inbox needed for the seeded accounts — email is captured in logs/test inbox per the Scope note.
> Individual attestors no longer exist — attestation is organization-based. The old "apply as attestor" user is gone.
> The **Google user** doing Drive-connector tests (§6) can be the same Google account — connector OAuth is per-user via Contributor's settings, independent of Google *login*.

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
| `Acme Advisory` | `acme-advisory` | Attestor-capability org |
| `Northwind Ops` | `northwind-ops` | Operator + Contributor capability org |
| `Scratch Org` | `scratch-org` | Throwaway for OR-7 removal, OR-9 transfer, OR-10 delete, OR-11 suspension |

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
| AU-2 | Password too short | — (new) | password `Short1` | Submit disabled / 422 "≥12 chars". |
| AU-3 | Role combo | — (new: Dual) | roles = Contributor + Operator | Accepted (Attestor is no longer a self-serve individual role). |
| AU-4 | Verify email | Contributor; negative: Unverified | token from captured email | Email verified; login allowed. Unverified account can't log in; resend-verification works. |
| AU-5 | Login wrong pass | Operator | `operator@auracles.dev` / `wrongpass1234` | 401 generic error. |
| AU-6 | Login OK | Operator | Operator row | Lands on role dashboard; refresh cookie set (HttpOnly); access token never in localStorage. |
| AU-7 | 2FA setup | Dual | enroll authenticator, enter current code | 2FA enabled; backup codes shown **once**; regenerate replaces them. |
| AU-8 | 2FA login | Dual | login then enter code at `/2fa-challenge` | Wrong `000000` → 401; valid code → in; backup code works once. |
| AU-9 | 2FA disable | Dual (re-enroll after) | valid TOTP required | Disabled; next login has no challenge. Re-enroll to restore bank state. |
| AU-10 | Forgot/reset | Suspend-me | email → reset link → new pass `Reset-Pass-2026` | Old pass fails, new works. |
| AU-11 | Logout | Operator | — | Protected route redirects to `/login`; refresh token revoked (back button can't restore session). |
| AU-12 | Rate limit | — | 6+ rapid failed logins on `operator@auracles.dev` | Throttled response. |
| AU-13 | Route guard | — (logged out) | hit `/dashboard/frameworks` | Redirect to `/login`. |
| AU-14 | Token refresh | Operator | stay idle past 15 min, then act | Silent refresh; no logout, no error flash. |

### 1b. Google sign-in

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| GA-1 | New Google user | Google user | "Continue with Google" on `/register`, email NOT registered | Passwordless account created, email pre-verified (no verification mail), lands on **onboarding role step**. |
| GA-2 | Roleless onboarding | Google user | pick Contributor and/or Operator on onboarding step | Role saved via role assignment; role dashboard reachable. Gated actions before choosing → role-required block. |
| GA-3 | Auto-link | Google-link | "Continue with Google" with Google email = existing password account | Signs into the SAME account (one user, two login methods); no duplicate account. |
| GA-4 | 2FA honored | Google user (enroll TOTP first) | Google login on the TOTP-enabled account | TOTP challenge before session issued; wrong code → 401. |
| GA-5 | Bad state | — | tamper `state` param on callback (or replay old callback URL) | 400; no session. |
| GA-6 | Set a password | Google user | forgot-password flow → set `Google-Pass-2026` | Both login methods now work. |
| GA-7 | Passwordless re-auth | Google user (before GA-6) | change email / request account deletion | NOT blocked on password: steps up via TOTP if enrolled, else email-confirmation path. Settings UI shows substitute factor, not a password field. |

## 2. Profiles

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| PF-1 | My profile | Contributor | open `/profile/me` | Own profile renders (display name, bio, roles, reputation, credentials). |
| PF-2 | Edit profile | Contributor | `/profile/edit`: display name `Test Contributor`, bio text | Saved; reflected on public profile. |
| PF-3 | Avatar upload | Contributor | PNG < 5 MB via upload → confirm | Two-step (presigned PUT + confirm); avatar renders. `.svg` or > 5 MB → rejected. |
| PF-4 | Banner upload | Contributor | JPEG < 5 MB | Same two-step; banner renders. |
| PF-5 | Public profile | Operator 2 | open Contributor's `/profile/[id]` | Public fields only — no email, no KYC status, no payout data anywhere in page or network tab. |

## 3. Explore / Discovery

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| EX-1 | Explore feed | — (logged out) | open `/explore` | Cards load fast; SSR (view-source contains content). |
| EX-2 | Search | — | query `growth` (or a published title keyword) | Relevant results; empty query handled. |
| EX-3 | Filters + paginate | — | category/price filter, next page | Correct subset; pagination stable. |
| EX-4 | Framework detail | — | open a published framework | Metadata, preview, price, attestation badges, reviews, reputation label, related frameworks. |
| EX-5 | Contributor profile | — | `/explore` → contributor link | Profile + reputation + verified credentials. |
| EX-6 | Org-owned framework | — | view a framework contributed by `Northwind Ops` (after §14) | Seller shown as the **organization** (name/logo), not the acting member. |
| EX-7 | Collections | — | `/explore/collections` + detail | Items + bundle price. |
| EX-8 | Attestor directory | — | `/attestors` public page | Approved attestor orgs listed; `/attestors/[orgId]` shows org profile + completed attestations. |
| EX-9 | Public org page | — | `/orgs/acme-advisory` | Public org profile by slug; no member emails/PII. |

## 4. Frameworks (Contributor)

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| FW-1 | Create draft | Contributor | title `Series A Fundraising Playbook`, desc, category, price `49.00` | Draft saved, listed in dashboard. |
| FW-2 | Price invalid | Contributor | price `0` or empty | Rejected (> 0 required). |
| FW-3 | Submit for review → publish | Contributor | submit draft (needs ≥1 processed artifact) | Can't publish until review passes; published shows in Explore. |
| FW-4 | Versioning | Contributor | create new version on published framework | New version; old retained; artifact source binding carried forward (see CN-8). |
| FW-5 | Unpublish + relist | Contributor | unpublish, then relist | Gone from Explore then back; existing licenses keep access throughout. |
| FW-6 | Delete draft | Contributor | delete an unpublished draft | Removed; published frameworks not deletable this way. |
| FW-7 | Non-owner edit | Operator 2 | edit Contributor's framework via URL | 403. |
| FW-8 | Preview artifact | Contributor | pick which artifact is the public preview | Detail page preview switches. |
| FW-9 | Analytics | Contributor; negative: Operator 2 | `/dashboard/frameworks/[id]/analytics` | Views/purchases render for owner; non-owner 403. |

## 5. Artifacts & processing pipeline

Upload = presigned PUT + confirm; then the `process_artifact` chain (virus scan → extract → PII → fingerprint → rarity → thumbnail → index). Status polls in the UI. **Actor throughout: Contributor** (owner of the draft), except where noted.

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| AR-1 | Upload valid | Contributor | small `.pdf` | Status walks to processed; thumbnail appears. |
| AR-2 | Wrong type | Contributor | `.exe` | Rejected (type error) — before S3 hit. |
| AR-3 | Oversized | Contributor | file > cap | 413/too-large — before S3 hit. |
| AR-4 | Virus | Contributor | EICAR file | Rejected with virus_detected; artifact unusable; ERROR logged. |
| AR-5 | PII detected | Contributor | PII-bearing doc | Pipeline flags PII; owner sees review state. |
| AR-6 | PII resolve | Contributor | resolve PII review (keep / redact) | Accept-redaction path produces redacted copy; framework can proceed. |
| AR-7 | Soft-fail ack | Contributor | artifact with a soft processing failure | Owner must acknowledge before submit proceeds. |
| AR-8 | Similarity notice | Contributor | upload artifact near-duplicating an existing one | Similarity notice shown; owner acknowledges to continue. |
| AR-9 | Rarity block | Contributor → Admin | upload highly-duplicative content | Publish blocked on rarity; **admin override** (AD-8) unblocks. |
| AR-10 | Delete artifact | Contributor | remove an artifact from a draft | Gone from list; S3 object cleaned up (orphan sweep tolerates it). |
| AR-11 | Stalled processing | Contributor + tester | kill worker mid-scan, wait for reaper (SC-17) or run it | Artifact fails cleanly, not stuck "processing" forever; re-upload works. |

## 6. Connectors (Google Drive)

**Actor throughout: Contributor** (Drive connected in setup), except CN-10.

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| CN-1 | Connect | Contributor | `/settings/integrations` → Connect Google Drive → OAuth consent | Connection listed as active. |
| CN-2 | Browse + import | Contributor | in framework editor: "Import from Drive", pick 2 files | Both copied in as artifacts, processed like uploads; **source binding** stamped (Drive badge on artifact). |
| CN-3 | Draft source preview | Contributor | view draft artifact imported from Drive | Live Drive thumbnail renders (proxied/cached — network tab shows OUR host, never a raw googleusercontent token URL). |
| CN-4 | Preview gating | Operator (licensed) + — | view same artifact after publish / as non-owner | No live preview — static/processed preview only. |
| CN-5 | Re-sync | Contributor | edit the file in Drive, click Re-sync on draft artifact | New copy pulled; byte change → **new immutable artifact version** (copy-on-write), old bytes retained for sold copies. |
| CN-6 | Re-bind | Contributor | attach a source to an unbound artifact / repoint to a different Drive file | Binding updates; next re-sync pulls from new source. |
| CN-7 | Detach | Contributor | detach source from artifact | Binding cleared; re-sync unavailable; artifact bytes untouched. |
| CN-8 | Version carry | Contributor | bump framework version (FW-4) | Source bindings carried to new version's artifacts. |
| CN-9 | Disconnect | Contributor | disconnect Drive in settings | Connection revoked; bound artifacts keep bytes, re-sync now fails gracefully (no crash/500). |
| CN-10 | GDPR revoke | Delete-me | run account deletion (GD-2) with a Drive connection | oauth connection revoked + purged. |

## 7. Purchase + Library (individual Operator)

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| PU-1 | Purchase (Stripe) | Operator | checkout `/checkout/[framework_id]`, success card | License created; confirmation; appears in `/library`. |
| PU-2 | Card declined | Operator | decline card | Decline surfaced; **no license**; transaction not stuck. |
| PU-3 | 3DS card | Operator | 3DS card | Auth challenge handled; license after completion. |
| PU-4 | NG routing | NG Operator | purchase | Routed to **Paystack**, NGN, Paystack test card. |
| PU-5 | Webhook replay | tester | replay same success webhook (or re-fire from provider dashboard) | Idempotent: still exactly one license. |
| PU-6 | Download artifact | Operator | purchased framework → download | Presigned URL (~15 min expiry); download audited. |
| PU-7 | Download w/o license | Operator 2 | hit download URL/endpoint for Operator's purchase | 403, no URL. |
| PU-8 | Purchase invoice | Operator | open invoice for a completed purchase | PDF renders (invoice number, seller block). |
| PU-9 | Refund | Admin (for Operator's purchase) | refund a purchase | Refund issued; license revoked/handled; balances consistent. |
| PU-10 | Collection checkout | Operator | `/checkout/collections/[id]` | Bundle license(s) created. |
| PU-11 | Buy own framework | Dual | buy own framework | Blocked (self-deal). |

## 8. Framework reviews

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| RV-1 | Review after purchase | Operator | rating + text on purchased framework | Review visible on detail page. |
| RV-2 | No license | Operator 2 | try to review same framework | 403. |
| RV-3 | Duplicate | Operator | review again | 409 — one review per buyer. |
| RV-4 | Org review | Org Owner (acting as `Northwind Ops` with org License) | post org review | Review attributed to the **organization**; reviewing member's identity NOT exposed in response/UI. |

## 9. Financials / Payouts (individual)

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| FN-1 | Payment method | Operator | add card — TOTP required | 2FA-gated; card saved masked (`****4242`). |
| FN-2 | Connect onboarding | Contributor | Stripe Connect / Paystack onboarding | Account link completes; payout account listed. |
| FN-3 | Earnings | Contributor | open earnings after a sale (PU-1) | Totals + history correct (platform commission deducted). |
| FN-4 | Payout no KYC | Dual (KYC unverified) | request payout | Blocked. |
| FN-5 | Payout no 2FA | Contributor | KYC ok, omit/wrong TOTP | Blocked; valid TOTP → accepted. |
| FN-6 | Payout amount | Contributor | `100.00` valid; then amount > balance | Valid accepted; excess rejected. |
| FN-7 | Purchase history | Operator | open purchases | All transactions with status. |

## 10. Projects + Workspace (individual)

Operator posts + funds; **Dual** is the bidding Contributor side.

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| PR-1 | Post project | Operator | title `Migrate billing to Stripe`, desc, category, budget min `500` / max `2000` | Posted; min<max enforced; budgets > 0. |
| PR-2 | Active-project cap | Operator | post 6 open projects | 6th rejected (409) — cap 5 active. |
| PR-3 | Proposal | Dual | scope text, bid `1500` | Bid recorded; operator sees it. |
| PR-4 | Proposal withdraw | Dual | withdraw own proposal (on a second project) | Withdrawn; no longer acceptable. |
| PR-5 | Accept proposal | Operator | accept Dual's proposal | Workspace created; membership set; other proposals closed. |
| PR-6 | Cancel acceptance | Operator | cancel acceptance (before funding) | Project back to open state. |
| PR-7 | Milestones | Operator | add milestones, **finalize** set, then reopen, edit, re-finalize | Finalize locks editing; reopen unlocks; funding requires finalized. |
| PR-8 | Fund milestone | Operator | amount `1500`, payment sheet | Escrow funded; operator payment method charged. |
| PR-9 | Amendments | Dual → Operator | Dual proposes amendment (scope/amount); Operator accepts / rejects; Dual withdraws another | State transitions correct; expired amendments revert (SC-6). |
| PR-10 | Submit deliverable | Dual | upload file + note | Operator notified; deliverable file scanned; Operator can download it (presigned). |
| PR-11 | Approve deliverable | Operator | approve | Escrow released to Dual; earnings reflect. |
| PR-12 | Auto-release | (beat) | let approval window lapse, no dispute | Escrow auto-releases (the only automatic release). |
| PR-13 | Dispute | Operator (or Dual) | raise dispute before approval | Escrow held; auto-release blocked. |
| PR-14 | Resolve dispute | Admin | resolution (full/partial refund) | Funds move per outcome; split transactions consistent; reputation effect. |
| PR-15 | Workspace messages | Operator + Dual (two browsers) | send messages + upload attachment | Delivered; attachments scanned + presigned; realtime updates across both. |
| PR-16 | Non-member | Operator 2 | open workspace/project URL | 403/404. |
| PR-17 | Close project | Operator | close own project | Closed; not biddable. |

## 11. Organizations — Core

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| OR-1 | Create org | Org Owner | create `Acme Advisory` (slug auto) | Org appears under `/dashboard/organizations`; creator = owner. |
| OR-2 | Org shell tabs | Org Owner vs Org Member | open org | Tabs scale with role/capabilities: Profile, Members always; Invitations/Teams/Attestor + more for admin; Danger Zone owner-only. |
| OR-3 | Logo upload | Org Owner | PNG < 5 MB via upload-url → confirm | Two-step verified upload; logo renders. Free-string logo keys via PATCH are impossible. |
| OR-4 | Invite member | Org Owner | invite `orgmember@auracles.dev` role member | Email with token link `/org-invitations/[token]`; pending listed. |
| OR-5 | Accept invitation | Org Member | open token link logged in | Joins org; shows in Members. Expired/consumed token → clear error (SC-13 expires pending ones). |
| OR-6 | Roles | Org Owner | promote Org Member 2 → admin (in `Acme Advisory`); demote test in `Scratch Org` | Admin tabs appear/disappear accordingly. |
| OR-7 | Remove member | Org Owner | remove a member (use `Scratch Org`) | Gone; their org access (library grants etc.) severed. |
| OR-8 | Teams | Org Owner | create team `Delivery`, add/remove Org Member + Org Member 2 | Team roster correct. |
| OR-9 | Transfer ownership | Org Owner → Org Member 2 | transfer (use `Scratch Org`) | New owner sees Danger Zone; old owner demoted. |
| OR-10 | Danger zone | Org Owner | delete `Scratch Org` | Org gone; members' dashboards clean. |
| OR-11 | Suspension | Admin; observed by Org Owner | suspend org (AD-13) | Banner shows; modification actions disabled; unsuspend restores. |
| OR-12 | RBAC | Org Member | hit admin-only org endpoints/tabs | 403 / tabs hidden. |

## 12. Organizations — Attestor capability (`Acme Advisory`)

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| OA-1 | NDA | Org Member 2 (+ Org Owner) | sign NDA | Required before attestation work; unsigned member blocked from review content. |
| OA-2 | Application | Org Owner | fill attestor application (draft → edit) | Draft persists. |
| OA-3 | Undertakings + tax doc | Org Owner | sign undertakings; upload tax document | Both recorded. |
| OA-4 | Nominate trial member | Org Owner | nominate Org Member 2 | Recorded on application. |
| OA-5 | Submit | Org Owner | submit application | Status pending; admin queue shows it. |
| OA-6 | Admin pipeline | Admin | verify-KYB → (optionally needs-info) → start-trial → approve | Each transition sticks; needs-info returns to org with reason; reject path also tested. |
| OA-7 | Directory listing | — | after approval | Org appears on `/attestors`. |
| OA-8 | Offer | Contributor requests (§13) → Org Owner | offer lands in org queue | Offer visible with expiry; **accept** assigns; **decline** releases; expiry handled by SC-2. |
| OA-9 | Reassign | Org Owner | reassign reviewing member mid-flight | New member continues; old loses access. |
| OA-10 | Review workspace | Org Member 2 (reviewing member) | start-review → content-ack → score each rubric dimension → add annotations → raise clarification | All persist; clarification notifies requestor. |
| OA-11 | Clarification respond | Contributor (requestor) | respond | Response visible to reviewer; unanswered ones expire (SC-4). |
| OA-12 | Report | Org Member 2 | submit report | PDF generated; requestor prompted to accept. |
| OA-13 | Accept report | Contributor | accept | Attestation published; **badge on framework detail**; escrowed fee releases to org (or SC-1 auto-release after window). |
| OA-14 | Dispute | Contributor → Admin | dispute report instead | Escrow held; admin resolution (AD-11) or refund. |
| OA-15 | Rating | Contributor | rate completed attestation | Stored; reflected on attestor org profile. |
| OA-16 | Money docs | Org Owner | open attestation invoice + earnings statement (+ annual) | PDFs render; routed to org legal identity. |
| OA-17 | Leak check | tester | inspect attestation/report responses | Reviewing member identity not exposed to requestor surfaces. |

## 13. Attestation (requestor side)

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| AT-1 | Request | Contributor | request attestation on own framework, pick `Acme Advisory` | Created; owner consent step. |
| AT-2 | Consent | Contributor | consent to content access | Consent recorded; expires if ignored (SC-3). |
| AT-3 | Fund | Contributor | pay attestation fee | Fee escrowed; offer dispatched to org (OA-8). |
| AT-4 | Artifact access | Org Member 2; negative: Org Member | assigned reviewer accesses framework artifacts | Presigned, audited; non-assigned org members → 403. |
| AT-5 | Status tracking | Contributor | watch `/attestations` | States progress: requested → offered → in review → report → accepted/disputed. |

## 14. Organizations — Contributor capability (`Northwind Ops`)

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| OC-1 | Activate | Org Owner | activate contributor capability | Active; framework creation as org possible. |
| OC-2 | Legal profile | Org Owner | fill org legal profile + upload tax document | Saved; required for settlement. |
| OC-3 | Org framework | Org Owner | create + publish framework under org identity | Explore shows org as seller (EX-6). |
| OC-4 | Sale settlement | Operator buys | purchase org framework | Earnings accrue to the **org**, not the acting member. |
| OC-5 | Org payout | Org Owner | org payout account + payout request | Routed to org legal identity; member's personal KYC/balance untouched. |
| OC-6 | XOR check | tester | inspect | Framework owned by org has no individual contributor attribution anywhere public. |

## 15. Organizations — Operator capability (`Northwind Ops`)

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| OO-1 | Activate | Org Owner | activate operator capability | Operator + Projects (+ Financials) tabs appear. |
| OO-2 | Org payment method | Org Owner | add card in org Financials — TOTP required | 2FA-gated; saved under org. |
| OO-3 | Buy as org | Org Owner | at checkout, buyer selector: personal vs `Northwind Ops` | Org purchase: License held by org; charged to org payment method. |
| OO-4 | Webhook idempotency | tester | replay org purchase webhook | Still one org License. |
| OO-5 | Grants | Org Owner | grant License to Org Member and to team `Delivery` | Grantees see item in org Library. |
| OO-6 | Granted download | Org Member | download artifact | Presigned; per-member audit row. |
| OO-7 | Ungranted | Org Member 2 (no grant in `Northwind Ops`) | try download | 403. |
| OO-8 | Revoke grant | Org Owner → Org Member | remove grant | Access gone immediately (403 on next download). |
| OO-9 | Billing | Org Owner | org Financials → Billing | Org invoices list (invoice number, date, doc type). *(Known scope gap: no per-purchase PDF for org purchases yet.)* |
| OO-10 | Org project | Org Owner | post project as org | `operator_org_id` set; personal projects unaffected. |
| OO-11 | Org project cap | Org Owner | 6th active org project | 409; owner's personal cap independent (personal 5 + org 5 both fine). |
| OO-12 | Org money path | Org Owner (Dual bids) | accept proposal → fund milestone (org card) → approve deliverable | Escrow funded by org, released to contributor; approval requires org admin. |
| OO-13 | Org dispute | Org Owner raises → Admin | dispute on org-operated project | Surfaces in admin dispute queue with org name; resolution + refund route to org. |
| OO-14 | Member exit | Admin/GDPR on Delete-me | remove/GDPR-delete a member holding grants | Their grants + team links removed; team-level grants for others survive. |

## 15b. Organizations — Team-scoped capability rights (`Northwind Ops`)

**Model under test.** Activating a capability (OC-1/OO-1) only makes the org
*eligible*. The derived role (Contributor / Operator / Attestor) is held by an
**owner/admin automatically**, and by a **plain member only through a team** that
has the capability enabled. Leaving that team (or disabling the capability on it)
revokes the role. UI: org → **Profile** tab → **Capabilities** card (activate);
org → **Teams** → per-team capability toggles + confirm dialog; expand a team to
add/remove members.

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| TC-1 | Owner/admin implicit | Org Owner → Org Admin | after OC-1/OO-1 activation, with no team assignment | Owner **and** admin already hold the role (Contributor can create as org; Operator sees Operator/Projects tabs). No team needed. |
| TC-2 | Plain member NOT auto-granted | Org Member (on no capability team) | after activation, inspect member's own dashboard | Member does **not** get the role from activation alone — no Contributor create / no Operator tabs. (Behavior change from the old org-wide grant.) |
| TC-3 | Enable before activate blocked | Org Owner | Teams → a team → toggle **Contributor** while org Contributor capability is **not** active | Toggle disabled with hint "Activate this capability for the organization first"; forcing the call returns **422**. |
| TC-4 | Enable on a team | Org Owner | activate Contributor (OC-1) → Teams → create/pick team `Delivery` → toggle **Contributor** on → confirm | Success toast; team row shows the Contributor chip; `refreshOrganization` updates pills live. |
| TC-5 | Member gains role via team | Org Owner → Org Member | add Org Member to `Delivery` (expand team → add member) | Member now holds Contributor: can create/publish a framework under the org identity. |
| TC-6 | Second member | Org Owner → Org Member 2 | add Org Member 2 to the same enabled team | Member 2 also gains the role — team grants apply to every member. |
| TC-7 | Remove from team revokes | Org Owner → Org Member | remove Org Member from `Delivery` | Role revoked immediately — member loses Contributor create ability. |
| TC-8 | Disable capability revokes all | Org Owner | toggle **Contributor** off on `Delivery` → confirm | Every remaining member of that team loses the role; owner/admin keep it (implicit). |
| TC-9 | Operator via team | Org Owner → Org Member | activate Operator (OO-1) → enable **Operator** on `Delivery` → member already on team | Member gains Operator: Operator/Projects surfaces appear for them. |
| TC-10 | Backfill (existing orgs) | tester | on an org that had a capability active **before** the team-scoping upgrade | An **"All members"** team exists holding the previously-active capabilities, with every pre-existing member on it → nobody lost access at cutover. |
| TC-11 | Attestor nominee auto-team | Org Owner → Admin | complete org attestor application nominating a plain member (§12) → admin approves | On approval, an **"Attestors"** team is created (if none) and the nominated member is added with attestor enabled → that member holds the attestor role. |
| TC-12 | Attestor staffing auto-team | Org Owner | accept an attestation offer (§13/OA flow) staffing a plain member as reviewing member | The staffed member is auto-added to the **"Attestors"** team → holds the attestor role; they can act on the review either way (review surfaces gate on staffing, not the role). |

> Authoritative role check (if UI is ambiguous): the derived grant is a
> `user_roles` row with `source='derived'` for that user and role
> (`contributor` / `operator` / `attestor`). Present ⇒ granted; absent ⇒ not.

## 16. Credentials

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| CR-1 | Add credential | Contributor | issuer, type, title, evidence upload → submit | Stored; status pending. |
| CR-2 | Admin queue | Admin | `/admin/credentials` | Pending listed; evidence viewable via presigned GET (audited). |
| CR-3 | Verify/reject | Admin | verify one, reject another | Verified badge on public profile; rejection reason shown to owner. |
| CR-4 | Unauthorized evidence | Operator 2 | request Contributor's evidence | 403. |
| CR-5 | Delete | Contributor | delete own pending credential | Removed. |

## 17. Reputation

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| RE-1 | New framework | — | freshly published fw | "New"/provisional label. |
| RE-2 | Accrue signals | tester + Admin | reviews + accepted attestation, recompute | Score/label appears; factors as labels only, no raw weights. |
| RE-3 | Penalty | (via PR-14) | dispute resolved against contributor | Score drops; decays over time. |
| RE-4 | Operator visibility | Dual (in-deal) vs — | view operator reputation | Visible to in-deal contributor/self/admin; absent from public Explore. |
| RE-5 | Manual recompute | Admin | TOTP + single subject | Recomputed; idempotent on re-run. |

## 18. Collections & Saved searches

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| CS-1 | Create collection | Contributor | name `Fundraising Pack`, add frameworks, publish | Public at `/explore/collections`; unpublish removes. |
| CS-2 | Save search | Operator | run search, save as `Growth tools` | Listed in `/settings/saved-searches`; "run" re-executes. |
| CS-3 | Alert | Contributor publishes + (beat) | new matching framework, run SC-15 | Alert email to Operator fires; no duplicate on re-run. |

## 19. Developer platform

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| DV-1 | Apply | Developer | company `Acme`, use-case, website `https://acme.dev` | Recorded; invalid URL rejected; withdraw works. |
| DV-2 | Admin review | Admin | approve application | Applicant unlocks portal. |
| DV-3 | API key | Developer | label `prod-key` | Key shown **once**; revoke kills it (401 after). |
| DV-4 | Partner call | tester (Developer's key) | partner API with key | OK; bad key → 401. |
| DV-5 | Webhook | Developer | url `https://acme.dev/hooks`, events | Saved; delivery on event; failed delivery retried (SC-14 + manual retry). |
| DV-6 | Usage/sales/tier | Developer | dashboards | Accurate; tier progresses (SC-16). |
| DV-7 | Partner payout | Developer | request payout | Recorded; commission clearing per SC-16. |

## 20. Notifications

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| NT-1 | Bell feed | Operator | trigger events (purchase, proposal, invitation) | Notifications appear. |
| NT-2 | Mark read | Operator | single + read-all | Unread count updates. |
| NT-3 | Org events | Org Member | org invitation/offer events | Delivered to right members per role. |
| NT-4 | Preferences | Operator | toggle types in settings | Respected by delivery. |

## 21. Settings

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| ST-1 | Email change | Operator | new email + step-up (password/TOTP; substitute factor if passwordless) | Confirmation mail to new address; confirm completes; old email notified. |
| ST-2 | Payment method | Operator | change + TOTP | 2FA required. |
| ST-3 | Payout accounts | Contributor | add/remove | KYC-gated for payout use. |
| ST-4 | KYC | Dual | start verification session | Status pending → admin review (AD-3) → verified. |
| ST-5 | Sessions | Operator | view; revoke one; revoke all | Revoked session logged out. |
| ST-6 | Consent | Operator | view/update consent records | History retrievable. |
| ST-7 | Integrations | Contributor | see §6 | — |

## 22. Admin

**Actor: Admin** throughout; targets named per row.

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| AD-1 | Users / suspend | Admin → Suspend-me | suspend, then unsuspend | Suspended can't log in; audited. |
| AD-2 | Roles | Admin | change a user's roles | Takes effect on next request. |
| AD-3 | KYC review | Admin | approve Contributor's / reject Dual's pending KYC | Status updates; payout gate follows. |
| AD-4 | Moderation | Admin | flag/remove content via queue | Works. |
| AD-5 | Frameworks | Admin | suspend + reinstate a framework | Hidden from Explore while suspended; licenses unaffected. |
| AD-6 | Licenses | Admin | inspect license list | Renders; no PII overexposure. |
| AD-7 | Escrow override | Admin | release / refund an escrow | Funds move; audited; CRITICAL-level guard rails hold. |
| AD-8 | Rarity override | Admin | override a rarity block (AR-9) | Framework publishable. |
| AD-9 | Analytics | Admin | dashboard + export | Metrics render; export downloads. |
| AD-10 | Config | Admin | set reputation weights / windows | Validation (sum≈1) enforced; bad config 422. |
| AD-11 | Disputes | Admin | project + attestation dispute queues | Org-operated and org-contributor disputes appear with org names; resolve works. |
| AD-12 | Org-attestor apps | Admin | `/admin/org-attestors` | Full OA-6 pipeline drivable. |
| AD-13 | Organizations | Admin → `Scratch Org` | suspend/unsuspend org | OR-11 behavior. |
| AD-14 | RBAC | Operator | hit `/admin/*` | 403 + WARNING log. |

## 23. GDPR

| # | Flow | As | Inputs | Expect |
|---|------|----|--------|--------|
| GD-1 | Export | Contributor | request export; job runs | Download link delivered; includes org activity keys (library downloads, project postings, review authorship — ids+dates only, no org financials). Link dies after TTL (SC-11). |
| GD-2 | Delete | Delete-me | request deletion; grace period passes (SC-12) | Anonymized; org grants/team links stripped (OO-14); oauth connections revoked (CN-10). Cancel-within-grace also tested. |
| GD-3 | Deletion blockers | Dual (with in-progress project / held escrow) | request deletion | Blocked with explicit reasons; org-only activity does NOT block. |
| GD-4 | Consent | Contributor | view consent history | Retrievable. |

## 24. Scheduled / automatic tasks (Celery Beat)

Actor = tester/ops (no UI account) — you trigger the task, then verify effect as the account named in the referenced scenario.

**How to trigger without waiting:**
- Start scheduler + worker: `make beat` **plus** `make worker`.
- Or force-run one task now: `cd backend && uv run python -c "from app.workers.tasks.<module> import <task>; <task>.apply()"`.
- For expiry/overdue cases, set the relevant timestamp into the past in the DB, or lower the window in `platform_config`, then run the task. **Re-run once more to confirm idempotency** (no double effect).

| # | Task | Expect |
|---|------|--------|
| SC-1 | `attestation_beat.auto_release_attestations` | Accepted-but-unactioned attestation fee releases to attestor org after window. |
| SC-2 | `attestation_beat.expire_attestation_offers` | Unaccepted offers expire; no longer acceptable. |
| SC-3 | `attestation_beat.expire_owner_consent` | Stale owner consent expires; attestation can't proceed. |
| SC-4 | `attestation_beat.expire_attestation_clarifications` | Unanswered clarifications expire. |
| SC-5 | `attestation_beat.revoke_overdue_attestations` | Overdue assignments revoked/reassignable. |
| SC-6 | `projects_beat.expire_pending_amendments` | Unactioned amendments expire; state reverts. |
| SC-7 | `projects_beat.expire_open_proposals` | Stale proposals expire. |
| SC-8 | `projects_beat.auto_approve_deliverables` | PR-12 auto-release. |
| SC-9 | `projects_beat.close_expired_projects` + `auto_close_delivered_projects` | Expired/no-acceptance projects close; fully-delivered ones auto-close. |
| SC-10 | `projects_beat.escalate_disputes` + `attestation_beat.escalate_attestation_disputes` | Past-SLA disputes escalate to admin queue; escrow stays held. |
| SC-11 | `gdpr_beat.expire_data_exports` | Export file purged; link → 410. |
| SC-12 | `gdpr_beat.process_account_deletions` | Post-grace deletions processed. |
| SC-13 | `organizations_beat.expire_pending_org_invitations` | Stale org invitations expire; token link → clear error. |
| SC-14 | `partner_webhooks.retry_due_partner_webhooks` | Failed deliveries retried or exhausted. |
| SC-15 | `saved_searches_beat.dispatch_saved_search_alerts` | CS-3 alert; no dup on re-run. |
| SC-16 | `developer_beat.clear_partner_commissions` + `recompute_partner_tiers` | Commissions settle; tiers recompute. |
| SC-17 | `artifacts_beat.reap_stalled_artifacts` | Stalled processing rows failed cleanly; aged S3 orphans reconciled — **redacted copies and preview cache spared**; re-run = no double effect. |
| SC-18 | `scheduled.clear_expired_licenses` | Expired licenses revoke access; download blocked. |
| SC-19 | `attestation_beat.send_coi_resign_reminders` | Conflict-of-interest re-sign reminders fire. |
| SC-20 | `invoicing_beat.generate_annual_earnings_summaries` | Annual earnings statements generated. |
| SC-21 | `admin_beat.snapshot_daily_analytics` | Snapshot row written; admin analytics reflect it. |
| SC-22 | `reputation.recompute_reputation` | Scheduled recompute runs; idempotent. |

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

| # | Flow | Accounts |
|---|------|----------|
| 1 | Register → verify email → role selected. **Plus:** Google sign-up → onboarding role step → dashboard. | new + Google user |
| 2 | Contributor: create framework → upload artifact (pipeline completes) → submit → published. | Contributor |
| 3 | Operator: search → purchase → download. | Operator |
| 4 | Operator: create project → contributor bids → accepted → milestone funded → deliverable approved → escrow released. | Operator + Dual |
| 5 | Attestation (org): request → consent → fund → offer accepted → rubric review → report → requestor accepts → badge live → fee released to org. | Contributor + Org Owner + Org Member 2 + Admin |
| 6 | Contributor: payout request with 2FA. | Contributor |
| 7 | Org-operator: create org → invite member → activate operator → buy as org (TOTP card setup) → grant member → member downloads → org project money path (fund → approve → release). | Org Owner + Org Member + Dual |
| 8 | Org-contributor: activate contributor → publish org framework → sale settles to org. | Org Owner + Operator |

---

## Sign-off — live go-ahead gate

Live testing is authorized **only** when every row is green.

| Area | Description | Status | Signed | Date |
|------|-------------|--------|--------|------|
| Sections 1–24 | All feature scenarios pass (desktop + 375px) | ☐ | | |
| Cross-cutting | RBAC, acting-identity, mobile, errors, security, atomicity, empty/loading | ☐ | | |
| Critical flows | All 8 release-blocking flows pass | ☐ | | |
| Defects | No open Critical/High defects | ☐ | | |

**Live go-ahead granted by William:** ☐ — date: ________

### Defect log

| ID | Scenario | Severity | Description | Status |
|----|----------|----------|-------------|--------|
| | | | | |

---

## Live (post-go-ahead) — re-verify only the delta

After local sign-off, on live re-check only what differs from local — don't re-run the full matrix blind:

- [ ] Real env vars set on Render (all `sync:false` secrets) + Vercel, including Google OAuth client (login) AND Drive connector client.
- [ ] `drive.readonly` scope verification status — until Google approves, Drive connector limited to test users.
- [ ] `REDIS_URL` is `rediss://` Upstash base; app uses **DB 0 only**.
- [ ] Public health green: `https://<api>.onrender.com/v1/health` (no `:10000`).
- [ ] CORS allowlist = real Vercel origin (no `*`).
- [ ] Stripe/Paystack **live** webhooks registered + signing secrets set; replay-idempotency spot-check.
- [ ] S3 real buckets + least-privilege IAM; presigned URLs work; orphan-sweep age guard confirmed against real bucket before first beat run.
- [ ] ClamAV present in worker image (scan actually runs, not skipped).
- [ ] CI-gated deploy: Checks green → `deploy.yml` fires Render hooks.
- [ ] e2e `org-operator.spec.ts` passes in staging (pre-release gate).
- [ ] Smoke the 8 critical flows on live with test data before announcing to team.
