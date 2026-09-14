# Organizations end to end — design

Follows the 2026-09-13/14 rework (slices 1–3: step-up + admin console, onboarding journey,
attestation request → report). This document covers everything else an organization touches,
owner side and admin side, and is built in the four slices below. Locked decisions are
recorded in §Decisions once the human has chosen.

## Implementation status (2026-09-14)

All on `rework/step-up-admin-console`, unmerged.

| Area | Commits |
|---|---|
| Slice A: broken flows, money safety | 890848a1 |
| Slice B: owner journey (migration 0105) | 1a7510a0, ef792249 (e2e) |
| Slice C: org money | 5159cdce, 6ac68ba6, 2355d933 |
| Slice D: admin directory, detail API and page | 49c1244c, c9c2aa2a, 43c608f6, 0e01a144 |
| Decision 5: slug change (migration 0106) | 29bdd984, bbada042, 79e1133d |
| Slug race closed: creation and slug change both take a transaction advisory lock on `org_slug:{slug}` before their check (no migration; unique-violation 409 stays the backstop) | f81f925b |
| Owner Members tab names each member's teams (`OrgMemberResponse.teams`) | f81f925b |
| Admin money screens name organizations | bbada042, 79e1133d |
| Audit log org indexes (migration 0107) | 9c9bb88a |
| Money fixes: Paystack partner webhooks, payee told of failed bank payouts (migration 0108) | 7c4f3a09 |
| Split oversized money components; payouts panel on formatMoney | d02b4d88 |
| Fixed on the way: email action links, public profile 404, centering, nav order | 1350c29c, f7c19e7e, 41001c6e, 4bba0027 |

Carry-overs, not built:
- `admin-money-panel.tsx` (about 600 lines) and `org-attestor-financials-tab.tsx` (about 325
  lines) exceed the component size guideline.
- The admin payouts panel formats money with its own per-row formatter rather than
  `formatMoney`.
- Stripe `payout.failed` deliberately changes no payout status: the money sits in the
  connected account's Stripe balance, so re-crediting would pay twice.

## Why (survey, 2026-09-14, five parallel read-only surveys)

**Broken today**
- Ownership transfer is unreachable: the danger zone reads the members response as a bare
  array, the filter throws, the error is swallowed, the "New owner" list is always empty
  (`organization-danger-zone.tsx:49-51`).
- Org billing lists the currency code where the invoice amount should be
  (`org-billing-section.tsx:253-258`); `invoice.total` is never rendered.
- Org-owned frameworks are invisible to admins: the admin framework directory, suspended
  list, rarity and PII moderation queues all inner-join on `Framework.contributor_id`, which
  is NULL for org frameworks (`admin/service.py:850,1100,1945,2000`).
- Admins are asked to verify a business but cannot open its incorporation documents: no
  admin endpoint and no keys on `AdminOrgResponse`; "Verify organization" is enabled blind.
- A brand-new invitee loses the invitation: the token page sends them to
  `/login?next=…`, the "Register" link drops `next`, and the reconciliation notification
  never names the org.
- Removing a member cascades away their license grants with no audit and no notice.

**Nobody is told**
- Org created, profile changed, deactivated: no notification to any member. Deactivation
  copy promises deletion of "all data, members, teams"; the backend sets `deactivated_at`.
- Invitee never told of revoke or expiry; inviter's accept/decline notification links to
  the wrong page; expired invitations show as pending until a daily sweep.
- Capability self-activation, license grant/revoke, org purchase completed (the org's card
  was charged), purchase failed, framework suspended or published under the org: silent.
- Payout requested, completed, failed, invoice ready: silent. Orgs have no payout history.
- KYB submission: no confirmation to the owner.

**Dead ends and hidden state**
- Members, invitations and teams tabs are hidden until KYB is verified, with no explanation.
- A revoked or expired org license disappears from the library rather than showing as such.
- Failed purchases appear on no org surface.
- Payout blocked: "not payout-eligible" with no reason (KYB, payout account, tax document,
  minimum, suspension) and the minimum is fetched but never shown.
- Suspension reason is invisible to admins and erased on reinstate; no admin sees who
  suspended an org, when, or its history. There is no admin org detail view at all.
- Public org profile exists but nothing links to it; owners never see their slug or URL.
- Deactivation is one-way with no admin reactivate.

**Errors**
- Org surfaces read `error.detail.error_code` while most endpoints return a string
  `detail`, so real messages ("Transfer ownership before removing the owner", 409 duplicate
  invite, 429) collapse to a generic sentence; dict details leak raw codes
  (`kyb_not_verified`, `org_suspended`, `capability_suspended`).
- `describeGeneratedError` handles string and list details only.

**Vocabulary and design system**
- Invitations, roles, frameworks, library items, payouts, admin directory status and the
  public profile all bypass `StatusPill`; framework lists hardcode semantic hexes; the NDA
  panel is hardcoded light mode.
- Admin org directory is a six-column table with horizontal scroll on phones.
- Sub-44px targets: members and invitation actions, teams icons, grant revoke (16px icon),
  logo zoom slider, public profile button.

**Security and money**
- Org purchase spends the saved card with no step-up; adding a payout account has no
  step-up; payout request has no idempotency key; any org admin can drain the balance.
- Public `GET /orgs/{slug}` is unauthenticated and not rate-limited; `website` accepts any
  scheme and is rendered as a link.
- Incorporation document upload, removal and KYB submit carry no step-up while the legal
  profile write does. Member search returns deactivated and suspended users.

**Tests**
- No component tests for members, danger zone, logo uploader, invitation accept, org
  projects or library pages; `tests/e2e/organizations.spec.ts` cannot pass (wrong selectors,
  wrong routes) and is not skipped.

## Decisions (human, 2026-09-14)

1. **Full admin org detail page** at `/admin/organizations/{orgId}`: overview, members,
   capabilities, verification documents, financial summary, frameworks and licenses,
   attestations in flight, audit trail.
2. **Invite anytime.** Members, invitations and teams are open from day one; capabilities
   stay gated on business verification.
3. **Owner-only payouts, admins purchase.** Payout requests and payout-account changes are
   owner-only with step-up and every owner is notified; org admins can still purchase
   (step-up added) and manage cards.
4. **Soft close, admin can reopen.** Deactivation keeps today's soft close; copy says the
   organization is closed and hidden with data retained; members are notified; admins get
   reactivate; blocked while a capability is active or money is pending.

5. **Owners can change the slug** (human, 2026-09-14, after seeing their org stuck on the old
   placeholder `acme-corp`). Owner only, behind step-up. Previous slugs stay reserved to the
   organization and `/orgs/{old}` redirects to the current slug, so shared links keep working
   and nobody else can claim an old slug to impersonate the organization. Taken or reserved
   slugs are refused with 409; the change is audited and other owners are notified. Admins do
   not get a slug editor.

Also fixed on the way (1350c29c): every "Open in Auracles" email button rendered a
path-only href; the renderer now pins action links to the frontend origin.

## Design

### Slice A — correctness and money safety

Backend
- Admin framework queries left-join users and orgs; `AdminFrameworkItem` gains
  `organization_id`/`organization_name`; org frameworks appear in the directory, suspended
  list, and moderation queues.
- `revoke_license_grant` audits the acting member. Member removal explicitly revokes the
  member's grants with an audit row (no silent cascade) and notifies the member.
- `GET /orgs/{slug}` rate-limited; `website` validated to `http(s)`.
- Step-up on: org purchase, payout-account onboarding, incorporation document add/remove,
  KYB submit. Payout request takes an idempotency key (`org_payout:{org}:{client_key}`).
- Consistent error details: every org route raises `{"error_code", "message"}`;
  `describeGeneratedError` reads `message` first, then string, then list.

Frontend
- Danger zone reads `result.data.members`; transfer works; failed member load is shown.
- Billing shows `formatMoney(invoice.total, invoice.currency)`.
- Register link preserves `next`; the token page decline calls the decline endpoint.
- `ConfirmDialog` gains `confirmDisabled` so the deactivate guard is visible, not silent.

### Slice B — owner journey (create → profile → people → wind-down)

- Creation dialog: slug preview with the public URL, "slug and country cannot be changed
  later" copy, server errors shown as messages.
- Profile: public URL with copy button and link, created/verified dates, member count,
  role rendered through `describeStatus`; `update_organization` writes an audit row.
- Invitations: `StatusPill` for status; history filter (pending/accepted/declined/revoked/
  expired) with expiry computed live; resend; invitee notified on revoke and expiry;
  inviter notification links to the org members page; invite CTA on the Members tab.
  Members/invitations gating per Decision 2.
- Members: role pill, teams shown per member, 44px targets, one shared `CAPABILITY_LABELS`.
- Teams: 44px targets, shared pills.
- Deactivation per Decision 4: copy matches behaviour, members notified, admin reactivate.
- NDA panel on tokens; library cards and framework lists on `StatusPill`
  (`PRESENTATION` gains `pipeline_failed`, `pipeline_passed`, `unpublished`, `processing`,
  `expired`, `revoked`).
- Notifications: `org_license_granted`, `org_license_revoked`, `org_framework_suspended`
  (reason), `org_framework_published`, `org_purchase_completed`, `org_purchase_failed`,
  `org_deactivated`, `org_kyb_submitted` (owner ack). Migration adds the enum labels.
- Library shows expired/revoked licenses as such; failed purchases listed under billing.

Slice B notes (2026-09-14): per-member team names on the Members tab need `teams` on
`OrgMemberResponse` and move to slice D with the admin members view; "library shows
expired/revoked licenses" and "failed purchases under billing" need backend list changes and
move to slice C. Register → verify → login now carries `next` end to end.

### Slug change (Decision 5)

Backend: migration adds `org_slug_history (org_id, slug unique, created_at)` and the
`org_slug_changed` notification label; `PATCH /v1/orgs/{org_id}/slug {slug}` owner-only with
step-up, same slug rules as creation, 409 when the slug belongs to another org now or in
history; old slug written to history, audit `org_slug_changed` {from, to}, other owners
notified. `GET /v1/orgs/{slug}` resolves a historical slug and returns the org with
`canonical_slug`. Frontend: the profile summary gains "Change slug" for owners (dialog with
the new public URL preview and a warning that the old link will redirect); `/orgs/[slug]`
redirects permanently when `canonical_slug` differs.

### Slice C — org money

- `formatMoney` everywhere on org financial surfaces; minimum payout shown; eligibility
  checklist (KYB verified, payout account verified, tax document, above minimum, not
  suspended) with a link per unmet item, driven by a new `payout_eligibility` field on the
  earnings response rather than a 403.
- Org payout history: `GET /orgs/{org}/financials/payouts` and a list on the tab with
  `StatusPill` (`PRESENTATION` gains payout statuses).
- Notifications: `org_payout_requested` (owners), `org_payout_completed`,
  `org_payout_failed` (owners + requester), `org_invoice_ready`, `org_purchase_completed`,
  `org_purchase_failed`, `org_license_granted`, `org_license_revoked`,
  `org_framework_suspended`, `org_framework_published` (labels already migrated in
  2026_09_14_0105; slice C adds the senders).
- Library lists expired and revoked licenses with their status; billing lists failed
  purchases with the failure reason.
- Payout authority per Decision 3.

### Slice D — admin

- **Admin org detail** `/admin/organizations/{orgId}` (per Decision 1): overview (status,
  suspension reason + actor + date, history), members with roles and teams, capabilities
  (existing dialog inline), verification (legal profile, incorporation and tax documents
  via new `GET /admin/orgs/{id}/kyb/documents` presigned, verdict with reason), financials
  summary (balance, payouts, purchases, invoices) via `GET /admin/orgs/{id}/financials`,
  frameworks and licenses, attestations in flight, audit trail
  (`GET /admin/audit-logs?org_id=`).
- Directory: card-stack on mobile, KYB column, `StatusPill` status, link to detail.
- `AdminOrgResponse` gains `suspension_reason`, `suspended_by`, `kyb_status` already; reinstate
  keeps history in audit and the detail shows it.
- Payouts, transactions, trace and invoices panels resolve and link org names; `org_id`
  filter on each.
- Admin deactivate/reactivate per Decision 4.

## Security

Every new admin read is behind `require_role("admin")`; document URLs are presigned for 300s
and audited. Every new sensitive write is behind `require_step_up_after(...)`. Notifications
carry reasons but never document URLs or account numbers. Org `website` is scheme-checked.

## Tests

Per slice: backend integration per endpoint (401/403/2xx, step-up refusals, notification
recipients), unit per service rule; vitest per component state; Playwright
`organizations.spec.ts` rewritten against real selectors: create → invite → accept →
transfer → deactivate; `admin-trust-console.spec.ts` extended with the org detail page.
