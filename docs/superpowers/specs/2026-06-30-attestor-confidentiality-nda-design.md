# Attestor Confidentiality NDA — Design Spec

**Date:** 2026-06-30
**Module:** Attestation / Onboarding (Module 1 follow-up)
**Status:** Approved — ready for implementation plan

## Purpose

Attestors download real contributor framework content through 2b's presigned-URL
access package. That model is **not DRM** — nothing technical prevents an attestor
from saving a file. The protection is legal deterrence.

Two layers were intended:

| Layer | Scope | State | Status before this work |
| ----- | ----- | ----- | ----------------------- |
| Per-accept content-use acknowledgment | Narrow — "won't misuse *this* framework I am about to review" | `attestations.content_ack_at` / `content_ack_version` | ✅ built in 2b (Task 6) |
| One-time onboarding confidentiality / non-use NDA | Broad blanket — "everything I ever access as an attestor is confidential and non-use; breach attracts legal action" | `attestor_applications.confidentiality_signed_at` | ❌ this spec |

This spec adds the second layer: a one-time, perpetual confidentiality/non-use
agreement signed during attestor onboarding, gating activation.

## Locked decisions

| # | Decision | Choice | Rationale |
| - | -------- | ------ | --------- |
| 1 | Gate point | **Activation prerequisite** | Add `confidentiality_signed_at` to `_missing_activation_prerequisites`. An application cannot activate into an `AttestorProfile` without it — the same gate already used for `coi_signed_at`. Only activated attestors receive offers, so offer-acceptance needs **zero new code** and fails closed at the role boundary. |
| 2 | Lifecycle | **Perpetual, single timestamp** | One `confidentiality_signed_at` timestamp, no expiry, no version. A confidentiality/non-use obligation does not lapse (unlike COI declarations, which expire at 365 days because the underlying facts go stale). |
| 3 | Backfill | **None — pre-launch** | No real attestors are activated in production yet. The new column is nullable; the prerequisite blocks only future activations. No migration data backfill, no retroactive re-consent. |
| 4 | Capture surface | **Separate endpoint** | A dedicated sign endpoint, not folded into the COI submit flow. COI expires and refreshes on a 365-day cycle; the NDA is perpetual. Coupling the two would entangle independent lifecycles. |

## Architecture

The feature mirrors the existing conflict-of-interest (COI) signing pattern
end-to-end. Every touch point has a direct COI analogue already in the codebase.

| Concern | COI analogue (existing) | NDA (new) |
| ------- | ----------------------- | --------- |
| Column on `attestor_applications` | `coi_signed_at` (`models.py:239`) | `confidentiality_signed_at` |
| Column on `attestor_profiles` | `coi_signed_at` (`models.py:338`) | `confidentiality_signed_at` |
| Capture service method | `sign_coi` (`application_service.py:251`) | `sign_confidentiality` |
| Capture endpoint | `POST /attestor/applications/{id}/coi` (`router.py:548`) | `POST /attestor/applications/{id}/confidentiality` |
| Activation gate | `_missing_activation_prerequisites` (`application_service.py:854`) | append `confidentiality_signed_at` |
| Profile copy on activation | `activate_attestor` (`application_service.py:872`, both create + update branches) | copy `confidentiality_signed_at` |
| Response schema field | `AttestorApplicationResponse.coi_signed_at` (`schemas.py:191`) | `confidentiality_signed_at` |

## Components

### 1. Data model + migration

Add a nullable, perpetual timestamp to **both** tables:

```python
confidentiality_signed_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True),
    nullable=True,
)
```

- `AttestorApplication` (`models.py`, near `coi_signed_at:239`)
- `AttestorProfile` (`models.py`, near `coi_signed_at:338`)

New Alembic migration `2026_06_30_0046_attestor_confidentiality_nda.py` (head is
`2026_06_30_0045`). `add_column` nullable on both tables. Downgrade drops both
columns. Backwards-compatible — nullable, no data backfill.

### 2. Capture — endpoint + service method

**Schema** (`schemas.py`): request body

```python
class ConfidentialityAgreementRequest(BaseModel):
    """Attestor acceptance of the one-time confidentiality / non-use agreement."""
    accept: bool
```

**Service** `sign_confidentiality` (`application_service.py`), mirroring `sign_coi`:

- `with_for_update()` lock, scoped to `application_id` **and** `user_id` → 404 if not found (deny-by-default, no existence leak)
- `payload.accept is False` → `HTTPException(422, "Confidentiality agreement must be accepted.")`
- `application.status == "active"` → `HTTPException(422, "Confidentiality agreement is locked once the application is active.")`
- **Idempotent:** if `confidentiality_signed_at` is already set, return the application unchanged (no timestamp overwrite, no second audit). Re-accept is a 200 no-op.
- Otherwise set `confidentiality_signed_at = datetime.now(UTC)` and write audit `attestor_confidentiality_signed` (metadata: `application_id` only — no PII, no document contents)

**Endpoint** `POST /attestor/applications/{application_id}/confidentiality`
(`router.py`), thin — parse → `sign_confidentiality` → `AttestorApplicationResponse`.
Summary/description note it records the agreement and does not change onboarding status.

### 3. Gate + profile mirror

- `_missing_activation_prerequisites` (`:854`): append `"confidentiality_signed_at"`
  to `missing` when `application.confidentiality_signed_at is None`. This is the
  entire enforcement — activation blocks until signed; offer-accept is untouched.
- `activate_attestor` (`:872`): copy `confidentiality_signed_at` from application to
  profile in **both** branches (new-profile create ~`:989` and existing-profile
  update ~`:1009`), alongside the existing `coi_*` copies.

### 4. Response schema field

`AttestorApplicationResponse` (`schemas.py:191`): add
`confidentiality_signed_at: datetime | None` so the onboarding UI can show signed
state.

## Data flow

```
Attestor onboarding
  -> POST /attestor/applications/{id}/confidentiality { accept: true }
       sign_confidentiality: lock row, owner-scoped
         accept false        -> 422
         already active       -> 422
         already signed       -> 200 no-op
         else                 -> set confidentiality_signed_at + audit
  -> (later) admin activates application
       _missing_activation_prerequisites: confidentiality_signed_at null -> blocked
       activate_attestor: copy confidentiality_signed_at -> AttestorProfile
  -> activated attestor receives offers -> accepts (no extra NDA check needed)
```

## Error handling

| Case | Response |
| ---- | -------- |
| Application not found / not owner | 404 `"Attestor application not found."` |
| `accept = false` | 422 `"Confidentiality agreement must be accepted."` |
| Application already active | 422 `"Confidentiality agreement is locked once the application is active."` |
| Already signed | 200 — idempotent no-op |
| Activation attempted while unsigned | existing activation path returns its prerequisite-missing error including `confidentiality_signed_at` |

## Security

- Owner-scoped lock (`application_id` + `user_id`) → no cross-user signing, no
  existence leak (404 for both missing and not-owned).
- Audit `attestor_confidentiality_signed` records `application_id` only — no PII,
  no agreement text, no secrets.
- Fails closed: activation is impossible without the signature; the gate lives at
  the role boundary (RBAC/activation), not inside accept logic.
- Idempotent capture — safe to retry, no duplicate audit, no timestamp drift.

## Testing (TDD)

**Unit — `sign_confidentiality`:**
- accept `true` on a non-active application → sets `confidentiality_signed_at`, writes audit
- accept `false` → 422, no timestamp set
- non-owner / missing application → 404
- application `active` → 422
- already signed → idempotent 200, timestamp unchanged, no second audit

**Unit — activation gate:**
- `_missing_activation_prerequisites` includes `confidentiality_signed_at` when null
- activation **blocked** when unsigned; **succeeds** once signed
- activated profile mirrors `confidentiality_signed_at`

**Integration — endpoint:**
- `POST .../confidentiality { accept: true }` → 200, response shows signed timestamp
- `{ accept: false }` → 422
- non-owner → 404

## Scope / file summary

~6 files: 1 migration, 1 column on each of 2 models, 1 request schema + 1 response
field, 1 service method, 1 endpoint, 1 line in the activation-prerequisite gate,
2 lines in the activation profile copy.

## Out of scope

- Frontend NDA text + checkbox UI (separate frontend task).
- Backfill / retroactive re-consent for already-active attestors (none exist — decision 3).
- NDA text versioning and re-consent on text change (decision 2 — perpetual single text).
- Any change to 2b's per-accept acknowledgment — it stands alongside this, unchanged.
