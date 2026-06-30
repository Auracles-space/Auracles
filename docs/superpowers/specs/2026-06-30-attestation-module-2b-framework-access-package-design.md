# Attestation Module 2b — Framework Access Package (Design)

Version 0.1 · 2026-06-30 · Status: DRAFT (awaiting human review)

## Context

Workflow doc **Module 2 — Attestation Request Submission** (`docs/Auracles Attestation — Product Development Workflow.md` §2.5), with lifecycle touchpoints in §3.4 (first-accept-wins). Module 2a (request-submission reshape: `review_type`, structured `brief`, tiered fees, operator-initiated requests, 10-day SLA) is merged. Module 2b is the **Framework Access Package** that §2.5 describes and that §3.4 steps 4–5 ("revoke other cohort's preview / unlock full content for the accepter") gate.

Today those step-4/step-5 transitions are **status flips only** — there is no access layer behind them. Module 2b is that layer.

What already exists and is reused (not rebuilt):
- `app/modules/attestation/matching_service.py` — cohort offers, first-accept-wins (`accept_attestation_offer`), decline, SLA-overdue revoke (`revoke_overdue_attestations`), stale-offer expiry (`expire_stale_offers`), and `_can_view_attestation` (requestor / cohort / assigned attestor / admin).
- `app/modules/library/service.py::request_artifact_download` — the operator artifact-access pattern: license check → `s3.storage.presigned_get` → log row + audit. Module 2b mirrors this for attestors.
- Framework preview content: `frameworks.preview_artifact_id` + per-version `framework_version_artifacts.is_preview`. The preview package reuses these.
- 2a request flow: `request_attestation` creates a `pending_fee` Attestation + Stripe PaymentIntent + escrow hold, then (operator-initiated) notifies the framework owner.

## Goal

Give Attestors a secure, read-only access package per §2.5: an executive-summary **preview** for the matched cohort before acceptance, **full framework content** for the accepting Attestor only, automatic **revocation** on finalise/reassign/non-accept, and an **access-event audit trail** — without disturbing the merged 2a request flow or the downstream lifecycle. Close the IP-exposure hole that operator-initiated requests (2a) would otherwise open: a third party must not trigger free full access to a contributor's paid content without the owner's consent.

## Out of scope (explicit)

- **Report-authoring workspace** (drafting, evidence upload) — that is **Module 4 (Review Workspace)**. `AttestationUploadSession` already exists for it. 2b is the *read-access* package only.
- **No-download DRM / watermarking / proxied streaming** — violates CLAUDE.md "presigned URL only, never proxy file downloads," and is a large build for weak gain. "Read-only" is enforced legally + by audit trail, not technically. Watermarking noted as a future forensic deterrent.
- **One-time blanket attestor confidentiality / non-use NDA at onboarding** — onboarding (`AttestorApplication`) today captures CoI only, not confidentiality. The blanket NDA is a **Module 1 (attestor onboarding)** follow-up. 2b's per-accept acknowledgment is self-sufficient (states the binding terms inline). Flagged below.
- AMM consumption of `review_type` (Module 3) and any change to report/dispute/release logic beyond the mechanical access/consent plumbing.

## The four deltas

| # | Delta | Doc | In 2b? |
|---|-------|-----|--------|
| 1 | Owner-consent gate for operator-initiated requests | §2.5 (IP scope) | ✅ |
| 2 | Executive-summary preview for matched cohort | §2.5 | ✅ |
| 3 | Full-content unlock for accepting Attestor + per-accept acknowledgment | §2.5, §3.4 | ✅ |
| 4 | Access-event audit trail | §2.5 | ✅ |

## Lifecycle changes

Only the **operator-initiated** branch changes. Owner-initiated (the common path) is byte-for-byte unchanged.

```
owner-initiated:
  pending_fee (+PaymentIntent now, 2a) --funded--> matching --> offered --accept--> accepted --> ...

operator-initiated:
  pending_owner_consent   (UNPAID — no PaymentIntent yet)
    owner approve   -> issue PaymentIntent -> pending_fee --funded--> matching --> ...
    owner decline   -> cancelled
    timeout         -> cancelled
```

- New status value `pending_owner_consent` added to `attestation_status_enum`.
- In `request_attestation`: when `initiator_is_owner == False`, **skip PaymentIntent creation** and set status `pending_owner_consent` instead of `pending_fee`. The existing owner-notify hook fires here (re-targeted to "consent requested"). Everything else in 2a is untouched.
- Owner approve does exactly what 2a request-creation did: create the PaymentIntent + escrow hold, set `pending_fee`. The "awaiting payment after approval" step **is** the existing `pending_fee` state — no new "awaiting payment" status, and operator-abandons-payment is covered by the **existing** `pending_fee` expiry.
- No refund path on decline — nothing was charged before consent.
- Consent timeout: a Celery Beat task mirroring `expire_stale_offers` scans `pending_owner_consent` rows older than `attestation_owner_consent_hours` (default 72) and sets them `cancelled`.

## Entitlement model — derived from status, never stored

There is **no grant table**. Entitlement is computed at request time from the live `Attestation.status` + the caller's `AttestationOffer.status`. Status is the single source of truth, so revocation cannot drift out of sync.

```
scope_for(user, attestation):
  caller's offer.status == "offered"                          -> PREVIEW   (preview artifacts only)
  attestation.attestor_id == user.id
      AND attestation.status in {accepted, report_submitted, disputed}
      AND attestation.content_ack_at is not None              -> FULL      (all artifacts)
  else                                                         -> NONE      (403/404)
```

Revocation is the **absence** of an entitling status — no revoke action is written:
- Non-accepting cohort: their offer flips to `superseded` on accept (already happens in `accept_attestation_offer`) → PREVIEW drops.
- Accepter at any terminal status (`released`, `resolved`, `refunded`, `closed`, `cancelled`) → FULL drops.
- SLA-overdue revoke (`revoke_overdue_attestations`) clears `attestor_id` (already happens) → FULL drops.

Full-access status set is `{accepted, report_submitted, disputed}` — the Attestor keeps content through report drafting and dispute defense, and loses it at any terminal state. (`resolved` excluded — the dispute is over; see open decisions.)

## Per-accept content-use acknowledgment

Full content cannot unlock without a binding, per-framework acknowledgment recorded at acceptance — the timestamped, versioned evidence used in any enforcement action.

- `accept_attestation_offer` gains required request fields `content_ack: bool` and `ack_version: str`.
- `content_ack` not `true` ⇒ `HTTPException(422)`. Accept is rejected; nothing changes.
- On accept, set `attestations.content_ack_at = now()` and `content_ack_version = ack_version`.
- The FULL entitlement check requires `content_ack_at is not None` (see entitlement model). Accept is the unlock gate.

## Data model changes

One Alembic migration, additive.

### `attestation_status_enum` — new value

`pending_owner_consent`. (Postgres `ADD VALUE` cannot be cleanly dropped on downgrade — noted as an irreversible enum addition, standard for this codebase.)

### `attestations` table — new columns

- `content_ack_at timestamptz NULL` — when the accepting Attestor affirmed the content-use acknowledgment.
- `content_ack_version text NULL` — the agreement version affirmed.

(One accepter per attestation, so the acknowledgment lives on the row — no separate table.)

### New table: `attestation_artifact_access` (access-event log)

```
id              uuid pk
attestation_id  uuid fk -> attestations.id   (indexed)
attestor_id     uuid fk -> users.id
artifact_id     uuid fk -> artifacts.id
scope           text  ("preview" | "full")
ip_address      text  null
created_at      timestamptz default now()
```

Append-only audit of every presigned access issued. This trail is the enforcement evidence behind the legal control.

### platform_config seed

- Add `attestation_owner_consent_hours = 72`.

Downgrade: drop `attestation_artifact_access`, drop the two `attestations` columns, remove the config seed. (Enum value addition is not reverted.)

## Endpoints

All behind the authenticated-user dependency.

### 1. `POST /v1/attestations/{id}/consent`

Owner consent on an operator-initiated request.

- Body: `{ "decision": "approve" | "decline" }` (Pydantic `Literal`).
- **Authz: the target framework's owner only.** Any other caller (including the operator requestor) ⇒ `404` (deny by default; no existence leak).
- Valid only when status is `pending_owner_consent`; otherwise `409`.
- `approve` → create PaymentIntent + escrow hold (reuse 2a funding), set `pending_fee`, return the same funding-response shape 2a returns; audit.
- `decline` → set `cancelled`, set `closed_at`, audit.

### 2. `GET /v1/attestations/{id}/package`

The read-only access package.

- Authz: `_can_view_attestation` (requestor / cohort member / assigned attestor / admin); otherwise `404`.
- Returns: framework metadata (title, category, industry), the 2a `brief`, the computed `entitlement` (`preview` | `full` | `none`), and an artifact list scoped to entitlement — preview-eligible subset for `preview`, full set for `full`, empty for `none`.

### 3. `POST /v1/attestations/{id}/artifacts/{artifact_id}/access`

Issue an entitlement-checked presigned GET. Mirrors `library/request_artifact_download`.

- Compute entitlement; `none` ⇒ `403`.
- `preview` scope: the artifact must be preview-eligible (`framework.preview_artifact_id` or a version artifact with `is_preview = true`); otherwise `403`.
- `full` scope: any artifact belonging to the target framework.
- Artifact not part of the target framework ⇒ `404`.
- `s3.storage.presigned_get(..., ARTIFACT_DOWNLOAD_URL_TTL_SECONDS)` (reuse the 15-minute TTL).
- Write an `attestation_artifact_access` row (attestation, attestor, artifact, scope, ip) + audit log. Never log the presigned URL (CLAUDE.md).

### 4. Accept-offer (existing) — acknowledgment required

`accept_attestation_offer` / its endpoint gains required `content_ack: bool` + `ack_version: str` (see acknowledgment section). No other change to accept behaviour.

## File layout

- New `app/modules/attestation/access_service.py` — entitlement computation, package assembly, presign + access-log. Keeps `service.py` / `matching_service.py` from growing.
- Consent logic (approve/decline + deferred funding) → alongside the request/funding code it reuses (`service.py`, next to `request_attestation`).
- Consent-timeout Beat task → `app/workers/tasks/` (the attestation scheduled-tasks file), mirroring the existing offer-expiry task wiring.
- Schemas → `attestation/schemas.py`. Endpoints → `attestation/router.py`. Migration → `backend/migrations/versions/`.

## Security review (CLAUDE.md mandatory checklist)

1. **Who can call** — consent: framework owner only (non-owner ⇒ 404, no existence leak). package / artifact-access: `_can_view_attestation`. Presign gated on computed entitlement, recomputed every request.
2. **Input** — Pydantic on every body; `decision` and scope are `Literal`s, `content_ack` a bool.
3. **Money** — consent-approve issues the PaymentIntent via the existing 2a funding path; escrow service untouched. No refund path (nothing charged before consent). Decline moves zero money.
4. **File access** — presigned-only, never proxied. `preview` scope serves only preview-eligible artifacts; `full` requires `attestor_id == me` + entitling status + `content_ack_at`. Short TTL. URL never logged.
5. **PII / IP** — full content gated behind owner consent (operator-initiated) and a per-accept binding acknowledgment. No brief contents in logs (2a rule preserved).
6. **Audit** — every artifact access → `attestation_artifact_access` + audit log; consent approve/decline audited; acknowledgment timestamped + versioned.
7. **Abuse** — entitlement recomputed per request (no stale grant); revocation automatic via status; consent timeout prevents indefinite unpaid holds.

## Testing (TDD, RED→GREEN per behaviour)

**Unit** (`tests/unit/modules/test_attestation_*`):
- Entitlement matrix: cohort `offered` ⇒ preview; assigned + `{accepted, report_submitted, disputed}` + ack ⇒ full; assigned + accepted but no ack ⇒ none; terminal status ⇒ none; non-owner / cleared `attestor_id` ⇒ none.
- Consent approve ⇒ `pending_fee` + PaymentIntent issued; decline ⇒ `cancelled`; timeout task ⇒ `cancelled`.
- Operator-initiated `request_attestation` ⇒ `pending_owner_consent`, no PaymentIntent; owner-initiated ⇒ `pending_fee` (2a unchanged).
- Accept without `content_ack` ⇒ 422; with ack ⇒ sets `content_ack_at` / `content_ack_version`.
- Preview scope rejects a non-preview artifact (403); full scope serves it.

**Integration** (`tests/integration/test_attestation_*`):
- Consent endpoint: owner ⇒ 2xx; operator requestor / other user ⇒ 404; wrong status ⇒ 409.
- Package endpoint returns the correct scope + artifact subset per caller (cohort vs accepter vs outsider).
- Artifact-access presign: happy path issues URL + writes access row; insufficient entitlement ⇒ 403.
- Accept requires acknowledgment (422 without).

**Migration:** `alembic upgrade head` + `downgrade -1` — enum value added, two columns + table added and dropped, config seed added/removed.

## Open decisions (defaults chosen; human may veto at review)

1. **`resolved` in full-access set** — default: **excluded** (dispute resolved = review over). Alt: include until `released`.
2. **Consent timeout** — default: **72h**. Alt: 48h.
3. **Owner consent 2FA** — default: **no 2FA** (content-exposure consent, not money/payout). Alt: require 2FA.
4. **Attestor access TTL** — default: **reuse 15-minute** `ARTIFACT_DOWNLOAD_URL_TTL_SECONDS`. Alt: shorter for attestors.

## Downstream notes (no change required in 2b, but verified)

- `accept_attestation_offer` already performs the cohort `superseded` flip; preview revocation rides it automatically.
- `revoke_overdue_attestations` already clears `attestor_id`; full revocation rides it automatically.
- The blanket attestor confidentiality / non-use NDA belongs to **Module 1**; 2b's per-accept acknowledgment stands alone until then.
