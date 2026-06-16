# Credential Verification UI (+ evidence download) — Design

**Date:** 2026-06-15
**Status:** Approved (brainstorming)
**Area:** Frontend (Next.js, mobile-first, brand-book) + one small backend addition.

## Problem

The credential-verification backend shipped (manual Admin-driven lifecycle,
`/v1/credentials/*` + `/v1/admin/credentials/*`, verified creds on the public
contributor profile). Only the generated client SDK exists frontend-side — no
pages/components consume it. This builds the three UI surfaces plus the one
backend endpoint the chosen scope requires.

Backend spec: `docs/superpowers/specs/2026-06-15-credential-verification-design.md`.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Evidence file upload UI | **Build now** — presigned-POST → S3 → attach keys. |
| 2 | Admin/owner evidence viewing | **Add backend presigned-GET download endpoint** (admin + owner), audited. |
| 3 | Settings component | Split the 213-line `credential-manager.tsx` into container + form + card (>200-line rule). |
| 4 | Admin surface | New `/admin/credentials` page + panel + nav link. |
| 5 | Public surface | "Verified credentials" section on the SSR contributor profile. |
| 6 | Commits | **None this round** — leave changes uncommitted for review. |

## 1. Backend addition — evidence download

- Service `generate_evidence_download_url(db, requester_id, credential_id, key, is_admin) -> str`:
  loads the credential; validates `key in credential.evidence_file_keys`; owner
  (`credential.user_id == requester_id`) may fetch any status, admin may fetch
  any credential; otherwise 404 (not found) / 403. Returns a short-TTL
  `s3.storage.presigned_get(bucket, key, ttl)` URL. Writes an audit row
  `credential_evidence_download` (CLAUDE.md: artifact downloads always audited).
  Never logs the presigned URL.
- Routes (both → `CredentialEvidenceDownloadResponse {url: str}`):
  - Owner: `GET /v1/credentials/{credential_id}/evidence?key=<s3key>` (current user).
  - Admin: `GET /v1/admin/credentials/{credential_id}/evidence?key=<s3key>`
    (`require_role("admin")`).
- OpenAPI hand-edit + `pnpm run generate:api`.

## 2. Contributor/Attestor settings (`/settings/credentials`)

Rebuild `components/modules/attestation/credential-manager.tsx` into:
- `credential-manager.tsx` — container: loads `listCredentials`, owns error +
  list state, renders form + cards.
- `credential-form.tsx` — create/edit form. Fields: title, issuer, issued_date,
  expires_date (existing) **+ credential_type (text), issuer_type (select:
  institution|organisation|government|association), verification_url (url),
  reference_number (text)**. Evidence upload: call
  `createCredentialEvidenceUploadSession`, POST the file to the returned S3
  `url`+`fields`, then attach via `updateCredential({evidence_file_keys})`;
  handle 409 (scan pending — retry/poll) and 422 (infected/invalid) with inline
  errors. Editing a `verified`/`pending` credential shows an inline warning that
  changing title/issuer/issued_date/reference_number resets verification.
- `credential-card.tsx` — per-credential row: status badge
  (unverified|pending|verified|rejected, plus derived expired), metadata,
  evidence file list each with a **View** action (owner download endpoint →
  open presigned URL), `rejection_reason` callout when rejected, and actions:
  Edit, Delete, **Submit for verification** (shown when unverified/rejected;
  disabled until ≥1 of {evidence file, verification_url, reference_number}).
- `credential-status-badge.tsx` (or extend existing badge): low-opacity
  brand-book variants — verified=success, pending=warning, rejected=error,
  unverified=muted/neutral, expired=neutral outline.

## 3. Admin review queue (`/admin/credentials`)

- New route `(auth)/admin/credentials/page.tsx` (thin) → `admin-credential-review-panel.tsx`.
- Add nav link in `components/modules/admin/admin-workspace-shell.tsx`.
- Status filter (default `pending`; can switch to verified/rejected/unverified)
  via `listCredentialReviewQueue({ query: { status } })`.
- Each row: owner id, title, issuer, credential_type, issuer_type,
  reference_number, verification_url (external link), evidence files each with
  **View** (admin download endpoint), submitted_at. Actions: **Verify**
  (`verifyCredential`), **Reject** (`rejectCredential`, inline reason textarea,
  required). On a self-owned credential the backend returns 403 — surface that
  message inline rather than pre-hiding (backend is authoritative).

## 4. Public profile verified badges

- `(public)/explore/contributors/[id]/page.tsx` already receives
  `profile.verified_credentials`. Add a "Verified credentials" `<section>` after
  Published Frameworks: one badge/card per credential showing title, issuer,
  credential_type, issued_date, expires_date, and an `expired` muted state.
  Render nothing when the array is empty. No sensitive fields (backend strips).

## 5. Testing

- **Backend:** download-endpoint unit + integration — owner fetches own ✓, admin
  fetches any ✓, stranger → 403/404, key not in credential → 404, audit row
  written; migration unaffected. Full backend gate (`ruff`, `mypy`, `pytest
  --cov ≥80`).
- **Frontend (vitest + RTL):** status-badge status→variant mapping; submit
  button enable/disable gate (no evidence/url/reference → disabled); edit-reset
  warning shows for verified/pending only; admin verify/reject invoke the SDK
  with correct args and surface 403 on self-review; public section renders only
  verified creds and omits sensitive fields. Mobile check at 375px for the
  settings card, admin queue (card-stack on mobile, not horizontal scroll), and
  public section.
- **No commits** — leave all changes staged/uncommitted for review.

## Security / notes

- Download endpoint: owner-or-admin only, key must belong to the credential,
  short-TTL presigned GET, audited, URL never logged. Backend RBAC authoritative.
- Public payload already excludes evidence keys / verification_url /
  reference_number / review metadata — the UI must not request or render them on
  the public surface.
- Mobile-first: 44px touch targets, card-stack tables on mobile, full-screen
  modals/inline panels per project standard.

## Out of scope

- Issuer-API automated verification (separate future feature).
- Operator business verification (separate future feature).
- Bulk admin actions / pagination beyond existing list precedent.
