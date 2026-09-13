# Organization onboarding journey — design (slice 2)

Second slice of the 2026-09-13 organizations + attestation rework. Slice 1 (step-up sessions,
admin trust console) is `2026-09-13-step-up-and-admin-console-design.md`. Slice 3 (attestation
request → report) follows.

## Why

Survey of the owner's path (create org → business verification → capabilities → attestor
application → trial → members) found the owner is blind at every point an admin acts:

- Admins suspend an org or suspend/revoke a capability with **no reason field** and **no
  notification**. The owner sees one banner ("Modification actions are disabled") with no why,
  when, or what next. Capability revocation has no owner-facing UI at all.
- A **trial decision notifies nobody**. A **rejected attestor application renders as "Submitted"**
  (green) and the tab has no rejected branch, although the backend already permits a fresh
  application once the old one is rejected.
- Member removal, role change, and ownership transfer notify nobody. KYB submission pings no
  admin, while attestor submission does.
- The organizations list hides `kyb_status` and `suspended_at`: a pending or suspended org looks
  identical to a live one. Capabilities render as raw `contributor: pending`.
- Received invitations sit in Settings › Organizations behind a one-shot toast.
- Nine different words for "waiting" across KYB, application, gates, and trial. The shared
  `StatusPill`/`describeStatus` from slice 1 is used only in the admin console.
- The trial gate shows the nominee as a raw UUID. Become-attestor silently drops unverified orgs.

## Locked decisions (human, 2026-09-13)

1. **Reason required, stored, shown.** Every admin suspend/revoke of an org or capability takes a
   reason (5–500 chars). It is saved on the row, shown in the owner's banner and notification.
   Reinstate clears it.
2. **Fresh application after rejection.** The owner sees "Rejected" with the admin's feedback and
   can start a new application. The rejected row stays on record.
3. **Invitation inbox on the organizations list page.** Settings › Organizations keeps the
   membership list and links to the inbox.

## Design

### 1. Backend

**Migration** `2026_09_13_0103_org_status_reasons.py`: `organizations.suspension_reason text
null`, `org_capabilities.status_reason text null`; enum labels `org_suspended`,
`org_reinstated`, `org_capability_suspended`, `org_capability_reinstated`,
`org_capability_revoked`, `org_attestor_trial_decided`, `org_member_removed`,
`org_member_role_changed`, `org_ownership_transferred`. Downgrade drops the columns and purges
notification rows under the new labels (Postgres cannot drop enum values).

**Requests.** `OrgStatusReasonRequest {reason}` on `POST /v1/admin/orgs/{id}/suspend` and the six
`capabilities/{cap}/{suspend|revoke}` routes. Reinstate stays body-less. All remain behind
`require_step_up_after(require_role("admin"))`.

**Responses.** `OrganizationResponse.suspension_reason`. `MyOrganizationResponse.capability_reasons:
dict[cap, reason]` (only capabilities that carry one). `OrgAttestorApplicationResponse.trial_status`
and `trial_feedback` (latest attempt), so the owner's Trial gate can show a failed trial and the
admin's feedback rather than only the checklist's pass flag.

**Owner notifications** — one shared helper `notify_org_owners(db, org_id, ...)` in
`organizations/notifications.py`, dispatched after commit through
`dispatch_project_notification` (preference-gated in-app + email), category `account`:

| Event | Recipients | Type | Link |
|---|---|---|---|
| Org suspended / reinstated | owners | `org_suspended` / `org_reinstated` | `/dashboard/organizations/{id}` |
| Capability suspended / reinstated / revoked | owners | `org_capability_*` | `/dashboard/organizations/{id}` (attestor → `/attestor`) |
| Trial decided | nominee + owners | `org_attestor_trial_decided` | nominee `/attestor-trial`, owners `/attestor` |
| Member removed | the member | `org_member_removed` | `/dashboard/organizations` |
| Member role changed | the member | `org_member_role_changed` | `/dashboard/organizations/{id}` |
| Ownership transferred | new owner | `org_ownership_transferred` | `/dashboard/organizations/{id}` |
| KYB submitted | admins | existing `admin_review_pending` | `/admin/organizations` |

Suspend/revoke bodies carry the reason. Not notified: org created, self-activated capability,
invitation revoked (the actor already knows).

`attestor_trial_service._load_trial` orders applications by `created_at desc` so a fresh
application after rejection resolves to the live one.

### 2. Frontend

**Vocabulary.** Every owner-facing status renders through `StatusPill`/`describeStatus`. Waiting
on an admin is always **"In review"** (KYB `pending`, application `submitted`, trial
`submitted`). `unverified` → "Not verified"; KYB `rejected` → "Needs changes" (resubmit is
allowed); application `rejected` → "Rejected". The local pill copies in
`organization-capabilities.tsx` and `org-verification-panel.tsx` are deleted.

**Organizations list** (`/dashboard/organizations`): top section **Invitations** with
accept/decline (moved from Settings › Organizations, which now links here; the one-shot toast
stays). Each org card shows the KYB pill when not verified, a "Suspended" pill when suspended,
and capability pills with real labels.

**Org shell.** Suspended banner shows the reason, the date, and a support mailto. One banner
per suspended or revoked capability, with its reason, whichever tab is open (the affected tab
disappears from the bar, so the banner is the only trace). The capabilities card stays visible
(read-only) while suspended.

**Verification panel.** Shared pill; waiting copy "In review — we will notify you when an
administrator has decided."; rejected shows the admin notes under "Needs changes" and keeps the
form open.

**Attestor tab.** New `rejected` branch: red status, admin feedback, "Start a new application"
(calls create; the tab then shows the fresh draft). Activation gate renders suspended/revoked
with the reason. Trial gate shows the nominee's name via the members list. Trial outcome is
shown to the owner once decided.

**Become attestor.** Unverified orgs appear in the picker disabled with "Verify the business
first" and a link to verification rather than being dropped.

**Team capability toggles.** Hint distinguishes never activated / suspended / revoked.

**Admin console.** Suspend and revoke confirm dialogs gain a required reason field through one
shared `ReasonField` (`admin-organizations-list.tsx`, `attestor-capability-controls.tsx`; there
is no admin UI yet for contributor/operator capability status, the API alone carries it).
Reinstate unchanged. `ConfirmDialog` focuses its first field when confirm opens disabled.

### 3. Out of scope

Email template redesign; a full-page notifications route; per-member notification of org
suspension (owners only); slice 3 attestation flows.

## Security

Reason text is owner-visible: admins are told so in the dialog. Max 500 chars, no markup
rendered. All routes stay step-up gated; notifications are queued after commit and never
carry secrets.

## Tests

Backend: integration per admin route (422 without reason, 204 stores it, reinstate clears,
owner notified with the reason); unit for trial-decided, member-removed, role-changed,
ownership-transferred, KYB-submitted admin ping; migration up/down.

Frontend: vitest for list page (pills, inbox accept/decline), shell banners with reason,
verification panel states, attestor tab rejected + reapply, become-attestor picker, admin
reason dialogs. Playwright `org-onboarding.spec.ts` (mocked API): list shows In review +
Suspended, inbox accept, shell banner reason, rejected application → new draft.
