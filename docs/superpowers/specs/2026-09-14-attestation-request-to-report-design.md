# Attestation request → report — design (slice 3)

Third and last slice of the 2026-09-13 organizations + attestation rework. Slice 1 is
`2026-09-13-step-up-and-admin-console-design.md`, slice 2 is
`2026-09-13-org-onboarding-journey-design.md`.

## Why

Survey (2026-09-14) of the requestor path (request → fund → matching → review → report →
release/dispute) and the attestor-org path (offer → workspace → report → outcome):

- **No entry point.** Nothing on a framework's workspace or public page lets anyone request an
  attestation. The only path is the global nav item and a collapsed form on `/attestations`, and
  the picker only lists the caller's own frameworks, so the owner-consent machinery for
  operator-initiated requests is unreachable.
- **The requestor is never told it is over.** Release (accept or auto-release) notifies only the
  reviewing member. Raising a dispute sends the requestor no acknowledgement. Offer expiry and
  re-matching are silent. A lapsed clarification tells the attestor, not the requestor who
  missed it.
- **Release and refund are indistinguishable.** Both write `closed`; `released`, `refunded`,
  `resolved` exist in the enum and are never assigned. The pill reads "Closed" either way.
- **No way out after paying.** Withdraw exists only before payment. After funding there is no
  cancel, no refund request, no explanation.
- **Two status vocabularies.** `attestation-status.tsx` carries a "requestor" map used by the
  requestor pages *and* the admin detail modal; it labels `needs_admin` "Finding attestor" where
  the admin list says "Needs admin". The attestor tabs print raw enum values (`offered`,
  "report submitted", "pending owner_consent").
- **Attestor notifications point at the wrong page.** Every attestor-side link goes to
  `/attestations/{id}`, the requestor detail, not the org workspace.
- **Workspace has no clock.** Neither the offers tab, the queue, nor the workspace shows the
  completion deadline, the offer expiry countdown, or the dispute window. Match score renders
  as `0.873%`. On `disputed` and `revision_requested` the reviewer sees a locked form and none
  of the reason, notes, or new due date.
- **Dead endpoints.** Rating and invoice exist backend-side with no UI. Dispute category is
  hardcoded to `scope_error`. Offer decline captures no reason.

## Locked decisions (human, 2026-09-14)

1. **Use the existing `released` / `refunded` statuses.** Release paths (requestor accept,
   auto-release, dispute rejected) write `released`. Refund paths (admin refund, dispute
   upheld-refund) write `refunded`. `closed` stays in the enum as a legacy value and is still
   read as completed. No migration.
2. **Self-service withdraw until an attestor accepts.** While the request is `matching`,
   `offered`, or `needs_admin` the requestor can withdraw; the escrow is refunded on its rail,
   open offers are superseded, and each org holding an open offer is notified. Once accepted
   the affordance disappears and the page says why. The request ends `cancelled`.
3. **Entry points on the framework workspace and the public framework page.** Contributors
   request from their framework workspace; signed-in operators request from the public page
   (owner-consent flow). Both deep-link to the request form with the framework prefilled.

## Design

### 1. Backend

**Migration** `2026_09_14_0104_attestation_flow.py`: `attestation_offers.decline_reason text
null`; enum labels `attestation_withdrawn`, `attestation_clarification_expired`. Downgrade purges
notification rows under the new labels and drops the column.

**Status writes.** `release_service._release_and_close` → `released`; `dispute_service` rejected
→ `released`, upheld_refund → `refunded`, `refund_needs_admin_attestation` → `refunded`;
requestor withdraw-with-refund → `cancelled`. Reads that meant "settled" accept `released` and
`closed` (certification, invoice); reads that meant "finished" accept all of `released`,
`refunded`, `closed`, `cancelled`.

**Withdraw.** `POST /attestations/{id}/cancel` extended: in `matching` / `offered` /
`needs_admin` it refunds at the provider, refunds the escrow, supersedes open offers, writes
`attestation_request_withdrawn` with `escrow_id`, and notifies orgs with open offers
(`attestation_withdrawn`, link to their offers tab). `pending_owner_consent` behaves as today;
`pending_fee` still refuses (webhook race); `accepted` and later refuse with 409 and a
message that names the attestor.

**Decline reason.** `POST /orgs/{org}/attestation-offers/{id}/decline` takes an optional
`{reason}` (max 500); stored on the offer; exposed on `AdminAttestationOfferItem`.

**Responses.** `AttestationRequestResponse` gains `attestor_org_name` and `dispute` (latest:
`status`, `category`, `reason`, `outcome`, `resolution_notes`, `resolution_due_at`,
`resolved_at`), populated for requestor and attestor readers. `AdminAttestationOfferItem`
gains `decline_reason`.

**Notifications** (all through the existing `_dispatch`, which now takes a per-call `link`):

| Event | New recipient(s) | Type | Link |
|---|---|---|---|
| Released (accept / auto / dispute rejected) | requestor; org owners | `attestation_released` | requestor `/attestations/{id}`; org `/dashboard/organizations/{org}/attestations/{id}` |
| Dispute raised | requestor (ack) | `attestation_disputed` | `/attestations/{id}` |
| Offer expired, next cohort or needs-admin | requestor | `attestation_offer_expired` | `/attestations/{id}` |
| Clarification lapsed | requestor | `attestation_clarification_expired` | `/attestations/{id}` |
| Requestor withdrew | orgs with an open offer | `attestation_withdrawn` | `/dashboard/organizations/{org}/queue` |
| Dispute upheld-revise | reviewing member (body now says revise + due date) | `attestation_dispute_resolved` | workspace |
| Every existing attestor-side event | unchanged recipients | unchanged | workspace / offers tab instead of `/attestations/{id}` |

### 2. Frontend

**Vocabulary.** `StatusTag` and `STATUS_LABELS` in `attestation-status.tsx` are deleted. Every
attestation, offer, and dispute status renders through `StatusPill`. A requestor-facing key
map (`requestorStatusKey`) reads `needs_admin` as "Finding attestor" (info) because the admin
step is invisible to them; `report_submitted` reads "Report ready" for the requestor and
"Submitted" for the attestor/admin.

**Entry points.** `RequestAttestationLink` (ui-less link component) on the framework workspace
header (published frameworks) and on the public framework page for signed-in non-owners with
the operator or contributor role; both go to `/attestations?target={id}`. The request form
opens expanded when `target` is present and pins that framework (own or external, with an
owner-consent note); the own-framework picker remains.

**Requestor list.** Cards show pill + target title + attestor org (when assigned) + one
next-step line + the relevant date. Accept/dispute move to the detail page.

**Requestor detail.** Header pill; **Progress** card with the ordered steps (Requested → Paid →
Attestor assigned → In review → Report → Closed) marked done/current, attestor org name linked
to `/attestors/{orgId}`, dates from `accepted_at`, `completion_due_at`,
`dispute_window_ends_at`, `closed_at`; one **Next step** sentence per status. Decision block
on `report_submitted` shows the dispute deadline, a category select, and the evidence
minimum. **Withdraw** (ConfirmDialog, refund copy) while withdrawable. On `released`: rate the
attestor (1–5 + comment, once) and download the invoice. On `refunded` / `cancelled`: refund
copy. On `disputed`: dispute status, due date, resolution once decided.

**Attestor org.** Offers tab: `StatusPill`, target title, match score as a percentage,
"Expires in N h" countdown, decline through ConfirmDialog with an optional reason, no raw
ids, link to the workspace after accept. Queue tab: `StatusPill`, due date with overdue tone.
Workspace header: `StatusPill`, due date, dispute window, requestor brief summary; on
`disputed` the reason and category; on `revision_requested` the admin notes and new due date.
Report panel copy corrected for those states; the report column renders first on mobile.

**Admin.** Detail modal uses `StatusPill`; offer history shows the decline reason.

### 3. Out of scope

Rubric definitions served by the API; step-up on attestor routes; a notifications page;
non-framework targets in the form; admin SLA extension.

## Security

Withdraw refunds only the caller's own attestation, only while no attestor has accepted, only a
`held` escrow, through the shared provider refund leg with an idempotency prefix; audited with
`escrow_id`. `attestor_org_name` is public directory data. `dispute` is returned only to the
two parties. Decline reason is admin-visible only.

## Tests

Backend: release/refund status assertions updated; withdraw (403 stranger, 409 after accept,
refund + supersede + org notification, idempotent); recipients for release, dispute ack, offer
expiry, clarification expiry; link targets for attestor events; decline reason stored and
shown to admin; detail carries `attestor_org_name` and `dispute`; migration up/down.

Frontend: vitest for the status key map, requestor list/detail per status, withdraw dialog,
rating card, request form prefill, entry links, offers tab (percent, countdown, decline
reason), queue tab, workspace header, admin modal. Playwright `attestation.spec.ts` (mocked):
framework page → prefilled request form; detail progress + withdraw; released → rate; offers
tab countdown → workspace due date.
