# Attestation Module 6c — Badge & Provenance — Design

**Date:** 2026-07-02
**Build priority:** 6 (Settlement & Payout), sub-module **c** of 4.
**Status:** Approved for planning.

## 0. Module 6 decomposition

Module 6 (Settlement & Payout, workflow §6.1–6.5) splits into four independent
sub-modules, each its own spec → plan → implement cycle, built in this order:

| Sub-module | Scope | Workflow |
| ---------- | ----- | -------- |
| 6a Settlement (done) | Escrow settles attestation at 90/10; attestor earnings clear immediately. | §6.1, §6.2 |
| 6b Reputation (done) | Attestor as reputation subject; rating → score; Certified Attestor; feed AMM. | §6.4 |
| **6c Badge & Provenance** (this doc) | Version-locked attestation badge published on framework close; framework-page display + attestor public "Completed Attestations" + immutable provenance record, gated on `report_published_eligible`. | §6.3 |
| 6d Invoicing | Attestation tax invoice (requestor) + earnings statement (attestor) + annual summaries. | §6.5 |

## 1. Overview

6c closes the **trust-signal** side of the attestation loop. When an attestation
settles and becomes eligible (`report_published_eligible == True` on close), the
platform writes a permanent, immutable **badge / provenance record** capturing what
was attested, by whom, and against which framework version. That record surfaces on
the framework page and the attestor's public profile, and is preserved in full
(including negative determinations) as a private provenance trail.

**Deliberately provenance-first.** The badge is not computed live from mutable
profile/framework tables — it is snapshotted at publish time so it is tamper-evident
and immune to later attestor renames, credential changes, profile deactivation, or
framework version bumps. The public trust signal never silently changes.

## 2. Scope boundary

**In scope (backend):**
- New `attestation_badges` immutable snapshot table.
- Capture the attested framework version on the attestation (FK, stamped at request
  submission for framework targets).
- Write the badge snapshot synchronously inside the release/close transaction, for
  **all** closed+eligible outcomes (complete provenance).
- Three read surfaces: framework-page badge list (public, positive-only), attestor
  public "Completed Attestations" list (positive-only), owner/admin provenance view
  (all outcomes incl rejected).
- `newer_version_exists` computed per badge.
- OpenAPI contract update.

**Out of scope (other sub-modules / already done / deferred):**
- Escrow release + `report_published_eligible` stamping — done in Module 5.
- Reputation scoring (6b), settlement (6a), invoicing (6d).
- Frontend rendering — backend-first; frontend follows after contract regen.
- Admin badge **revocation** (fraud/takedown) — future module; 6c never mutates or
  deletes a provenance row.
- Explore **card** badge (`ExploreFrameworkCard.attestation_badge`) — unchanged;
  stays the compact positive-only signal it is today.

## 3. What already exists (reused unchanged)

- **`Attestation`** carries `review_type` (quality/compliance/expert/provenance =
  attestation **type**), `outcome` (approved/conditional/rejected = **determination**),
  `target_type`/`target_id`, `status`, `closed_at`, `report_published_eligible`,
  `report_key`.
- **`release_service._release_and_close`** sets `status="closed"` +
  `report_published_eligible=True` on accept / auto-accept / dispute-rejected. This is
  the single publish trigger point.
- **`framework_versions`** — immutable per-publish version history
  (`uq_framework_versions_framework_version`), `version VARCHAR(20)`. `frameworks.version`
  holds the current published version string.
- **`directory_service`** — public attestor directory; `_verified_credentials` already
  builds public-safe credential responses (title/issuer/type, **no** evidence file keys),
  and `_completed_attestations` counts completed work. 6c reuses the credential shape and
  extends the count into a list.
- **`GET /explore/frameworks/{framework_id}`** → `ExploreFrameworkDetail` — the public
  SSR framework page. Today exposes a single `attestation_badge` + `attestation_count`;
  6c adds the full multi-badge list.

## 4. Locked decisions

### 4.1 Version capture — FK at request submission

Add `attestations.framework_version_id UUID NULL` → `framework_versions.id`. Stamped
when a **framework-target** request is submitted (the version the attestor is contracted
to review). Nullable because non-framework targets (contributor/operator/credential)
have no framework version. The FK points at an immutable version row, so the attested
version and its exact artifact set are permanently resolvable.

Rejected alternatives: a bare version string (drifts from `framework_versions` truth, no
artifact link); capture at settlement (attestor reviewed the submission-time version — a
mid-review bump would record the wrong version).

### 4.2 Provenance — immutable snapshot table

New `attestation_badges` table. At publish, one durable row snapshots every displayed
field. Badge reads render from the snapshot, never from live profile/framework/credential
tables. Tamper-evident; decouples public reads from live PII tables.

Rejected alternative: live-join on read — badge fields would drift on attestor rename or
credential change, and every public read would hit live profile/credential tables.

### 4.3 Publish trigger — synchronous in the close transaction

`badge_service.publish_badge(att)` is called inside the same
`release_service._release_and_close` transaction that sets `status="closed"` +
`report_published_eligible=True`. Atomic — a badge exists exactly when the attestation is
eligible, with no "eligible but no badge" window. `INSERT ... ON CONFLICT (attestation_id)
DO NOTHING` makes it idempotent across retries. All snapshot inputs (attestor display
name, verified credentials, framework version via FK) are available at close.

Rejected alternative: async Celery task — eventual (badge lags close), needs its own
idempotency guard + eligibility re-check for no benefit here.

### 4.4 Rejected visibility — snapshot all, publicly show positive only

The badge row is written for **every** closed+eligible attestation, including rejected
("Not Approved") — the provenance record is complete. But public surfaces (framework
page, attestor completed list) render **positive only** (`approved`/`conditional`).
Rejected rows are visible only to the framework owner and admins.

Rationale: a public "Not Approved" badge chills attestation demand (a contributor who
requests attestation of their own framework and pays the fee would receive a public
scarlet letter) and creates a defamation/retaliation surface (esp. third-party-requested
rejections). Full transparency of positives + a private complete record satisfies §6.3's
determination enumeration via the provenance record and owner view without broadcasting
negatives to all viewers.

### 4.5 `newer_version_exists`

Per badge: `newer_version_exists = (framework.version != badge.framework_version)`.
Framework versions are monotonic on publish, so string inequality against the current
published version is sufficient; no semver ordering required. When a badge has no captured
version (legacy attestation created before 6c, `framework_version_id IS NULL`), the flag
is `False` and the version renders as `null`.

## 5. Data model

### 5.1 New table `attestation_badges`

```
attestation_badges
  id                   UUID PK
  attestation_id       UUID NOT NULL  FK -> attestations.id   UNIQUE
  framework_id         UUID NOT NULL  FK -> frameworks.id      (indexed)
  review_type          attestation_review_type_enum NOT NULL   -- type
  outcome              attestation_outcome_enum NOT NULL        -- determination
  attestor_id          UUID NOT NULL  FK -> users.id           (indexed)
  attestor_display_name TEXT NOT NULL                          -- snapshot
  credentials_snapshot JSONB NOT NULL                          -- public-safe list
  framework_version    VARCHAR(20) NULL                        -- snapshot string
  issued_at            TIMESTAMPTZ NOT NULL
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
```

- `UNIQUE(attestation_id)` — one badge per attestation; the idempotency key.
- Index `idx_attestation_badges_framework` on `framework_id` (framework-page read).
- Index `idx_attestation_badges_attestor` on `attestor_id` (attestor completed list).
- Immutable: rows are inserted at publish and never updated or deleted in 6c.

### 5.2 Alter `attestations`

```
ALTER TABLE attestations
  ADD COLUMN framework_version_id UUID NULL
    REFERENCES framework_versions(id) ON DELETE SET NULL;
```

Nullable; set only for framework-target requests at submission. `ON DELETE SET NULL` so a
framework-version deletion (not expected — versions are immutable history) cannot orphan.

Both changes ship in one Alembic migration. Round-trip (`upgrade head` /
`downgrade -1`) must succeed; no seed data.

## 6. Publish flow

```
release_service._release_and_close(attestation, ...):        # existing, Module 5
  ... existing escrow release + status transition ...
  attestation.status = "closed"
  attestation.report_published_eligible = True
  await badge_service.publish_badge(db, attestation=attestation)   # 6c, same txn
```

```
badge_service.publish_badge(db, *, attestation) -> AttestationBadge | None:
  if attestation.target_type != "framework":        # badges are framework-scoped in 6c
      return None
  if not attestation.report_published_eligible:      # defensive guard
      return None
  version = None
  if attestation.framework_version_id is not None:
      version = <framework_versions.version for that id>
  display_name = <attestor user display name>
  credentials = <public-safe verified credentials for attestor_id>   # reuse directory shape
  INSERT INTO attestation_badges (...)
    VALUES (attestation.id, attestation.target_id, attestation.review_type,
            attestation.outcome, attestation.attestor_id, display_name,
            credentials, version, attestation.closed_at or now())
    ON CONFLICT (attestation_id) DO NOTHING
  log INFO badge_published (module=attestation, action=publish_badge,
      attestation_id, framework_id, outcome)
```

Snapshots all outcomes (approved/conditional/rejected). Public read filters, not the
write, enforce positive-only visibility.

## 7. Read surfaces

### 7.1 Framework page — `ExploreFrameworkDetail.attestation_badges`

Enrich the existing `GET /explore/frameworks/{framework_id}` detail response with:

```
attestation_badges: list[AttestationBadgeDetail]
```

`AttestationBadgeDetail`: `id, review_type, outcome, attestor_id,
attestor_display_name, credentials (public-safe list), issued_at, framework_version,
newer_version_exists`.

- Public, no auth. **Positive-only** (`outcome in {approved, conditional}`).
- Multi-badge: all positive badges for the framework, most-recent `issued_at` first.
- `newer_version_exists` per §4.5.
- The existing single `attestation_badge` + `attestation_count` fields stay for
  back-compat; the plan decides whether the list supersedes them (no behavior removed
  without a migration note).

### 7.2 Attestor public profile — Completed Attestations list

New `GET /attestation/attestors/{attestor_id}/completed` (public).

Returns the attestor's **positive** badges as
`AttestorCompletedAttestation`: `framework_id, framework_title, review_type, outcome,
issued_at, framework_version`. Most-recent first. Complements the existing
`completed_attestations` count on the directory profile (§6.3 "logged in the Attestor's
public profile under Completed Attestations").

### 7.3 Owner/admin provenance view

New `GET /frameworks/{framework_id}/attestation-badges` (authenticated).

- RBAC dependency: caller must be the framework owner
  (`framework.contributor_id == user_id`) **or** hold the admin role. Otherwise 403,
  logged WARNING with `user_id` + attempted `framework_id`.
- Returns **all** badges for the framework incl rejected (full provenance), same field
  set as §7.1 plus nothing sensitive beyond it (credentials remain public-safe).
- 404 if the framework does not exist.

## 8. Error handling & edge cases

| Case | Handling |
| ---- | -------- |
| Non-framework target attestation closes | `publish_badge` returns `None`; no row. Badges are framework-scoped in 6c. |
| Retry / double close | `ON CONFLICT (attestation_id) DO NOTHING`; idempotent, no 500. |
| Legacy attestation (`framework_version_id` NULL) | Badge written with `framework_version = NULL`, `newer_version_exists = False`. |
| Rejected outcome | Snapshot written; excluded from public reads; visible in owner/admin view. |
| Framework bumped after attestation | `newer_version_exists = True`; prior badge unchanged (version-locked). |
| Multiple attestations per framework | One badge row each; all positives listed independently (multi-badge). |
| Framework version deleted | `ON DELETE SET NULL` on the attestation FK; badge already snapshotted its version string, unaffected. |
| Owner view by non-owner/non-admin | 403 + WARNING; deny by default. |
| Badge read for nonexistent framework | 404 (owner view); public detail already 404s. |

## 9. Security

- **Public surfaces** (§7.1, §7.2): no auth, positive-only, PII-safe — only public
  credential fields (title/issuer/type) and the attestor display name; never evidence
  file keys, never rejected determinations.
- **Owner/admin view** (§7.3): RBAC at the dependency layer (owner-or-admin); denial
  logged WARNING; deny by default.
- **Provenance integrity**: badge rows are insert-only in 6c; no update/delete path
  exists. Snapshot at publish is the tamper-evidence guarantee.
- **No secrets, no money movement, no escrow change.** 6c is downstream of settlement.
- **Audit/log**: `badge_published` at INFO on write; RBAC denials at WARNING.

## 10. Testing (TDD, RED → GREEN per behavior)

**Migration:** `attestation_badges` table + indexes + `UNIQUE(attestation_id)` created;
`attestations.framework_version_id` FK added; downgrade removes both cleanly.

**Version capture:** submitting a framework-target request stamps `framework_version_id`
to the framework's current published version row; non-framework targets leave it NULL.

**Publish (`badge_service.publish_badge`):**
- Close of an approved framework attestation writes a badge snapshotting type,
  determination, attestor name, public credentials, version, issued_at.
- Conditional and rejected also write a row (complete provenance).
- Non-framework target → no row.
- Called twice (retry) → single row (idempotent).
- Publish inside the close txn: after `_release_and_close`, the badge exists.

**Framework page (§7.1):** detail returns positive badges only; rejected excluded;
`newer_version_exists` True after a framework bump, False otherwise; multi-badge ordering.

**Attestor completed list (§7.2):** returns positive badges for the attestor; rejected
excluded; framework title present; ordering most-recent first.

**Owner/admin view (§7.3):** owner sees all incl rejected; admin sees all; non-owner
non-admin → 403; nonexistent framework → 404.

## 11. Blast radius

- **New:** `attestation_badges` table + model; `badge_service.py`
  (`publish_badge` + read helpers); schemas `AttestationBadgeDetail`,
  `AttestorCompletedAttestation`, owner-view response; two new endpoints
  (attestor completed, owner/admin view).
- **Modified:** one Alembic migration; `attestations` model (+`framework_version_id`);
  request-submission service (stamp FK); `release_service._release_and_close`
  (call `publish_badge`); `explore` detail service + `ExploreFrameworkDetail` schema
  (+`attestation_badges`); `contracts/openapi.yaml`.
- **No escrow change. No money movement. No change to settlement or reputation.**

## 12. Build slices (backend, TDD)

1. **Migration + models** — `attestation_badges` table, `attestations.framework_version_id`
   FK, ORM models.
2. **Version capture** — stamp `framework_version_id` at request submission (framework
   targets).
3. **Badge publish** — `badge_service.publish_badge` + wire into
   `release_service._release_and_close` (all outcomes, idempotent).
4. **Framework-page badges** — `ExploreFrameworkDetail.attestation_badges` (public,
   positive-only) + `newer_version_exists`.
5. **Attestor completed list** — `GET /attestation/attestors/{id}/completed` (public,
   positive-only).
6. **Owner/admin provenance view** — `GET /frameworks/{id}/attestation-badges`
   (owner-or-admin, all outcomes).
7. **OpenAPI** — contract update for the new/changed endpoints (frontend deferred).
