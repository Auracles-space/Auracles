# Framework Artifact Connectors — Phase B (Source Binding + Draft Live-Mirror Preview) — Design

- **Date:** 2026-07-08
- **Status:** Approved — ready for implementation plan
- **Author:** William Ikeji (architect) + agent
- **Module:** `frameworks` (artifacts) + `integrations`
- **Parent spec:** `docs/superpowers/specs/2026-06-28-framework-artifact-connectors-design.md`
- **Predecessor:** Phase A (import copy-in) — shipped (`44e5c15`, `2203a97`)
- **Related FRs:** FR-FWK-* (artifact upload, versioning, publish/review workflow), FR-GDPR-*

## Context

Phase A shipped the import connector: a contributor signs in to Google Drive, picks a file,
and Auracles **copies the bytes into our S3** and runs the standard pipeline. An imported
artifact is today indistinguishable from an uploaded one — it records **nothing** about where
its bytes came from.

Phase B delivers the "edit in Drive → reload → see it changed" ergonomic from the parent spec,
**without** weakening any marketplace invariant. It does two things:

1. **Source binding** — persist, per artifact, which external file its bytes came from.
2. **Draft live-mirror preview** — while an artifact is unpublished, show the *current* Drive
   thumbnail and a **"Source updated since import"** badge so the contributor sees their source
   has drifted and (in Phase C) can pull the latest.

Phase B does **not** move any new bytes. The live-mirror is a *visual signal*; re-pulling
changed bytes into a new version is Phase C (`resync` / re-bind). Every byte that becomes a
sellable artifact still lands in our S3 and passes the full pipeline exactly as in Phase A.

This spec records the decisions reached grilling the Phase B design on 2026-07-08.

## Locked decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Is the live-mirror a byte-less "bind" mode, or copy-in + change indicator? | **Copy-in stays** (Phase A behavior). B adds source-binding columns on the already-copied artifact and a draft change-indicator preview. No byte-less artifact class; `Artifact.file_key`/`file_size` stay `NOT NULL`; publish/pipeline invariants untouched. |
| 2 | Show a live thumbnail only, or also detect drift? | **Detect drift.** Store the source's `modifiedTime` at byte sync; on draft view compare against the current `modifiedTime` and render a "Source updated since import" badge. Uses `modifiedTime` (universal — Google-native docs expose no `md5Checksum`). |
| 3 | How does the live Drive thumbnail reach the browser? | **Cache-to-S3 + presigned.** Backend fetches `thumbnailLink` bytes with the stored token, `upload_bytes` to our S3, returns an existing-style `presigned_get` URL. Token never leaves the backend. **Host-allowlist** the `thumbnailLink` before the GET and **size-cap** the fetch. |
| 4 | Where does the thumbnail-cache freshness marker live? | **Versioned S3 key** — `…/source-preview/{modifiedTime}.png`. Freshness = `object_exists(current_modifiedTime)`. No Redis marker, no DB write on the read path, survives restarts; delete the old key on refresh to bound storage. |
| 5 | Backfill of existing artifacts (real uploads + Phase-A imports)? | Migration sets `source_kind` **NOT NULL default `upload`**. Phase-A imports collapse to plain uploads (no recorded source to mirror). Attaching a source to such an artifact is **Phase C re-bind**. |
| 6 | How is "preview never on sold/published surfaces" enforced? | **By construction.** A dedicated **owner-only, pre-publish** endpoint returns the preview in a **separate schema**; the source-preview URL/drift flag is **never** a field on the shared `ArtifactResponse` (which buyer/catalog/public paths serialize). Preview S3 objects deleted at publish; binding columns persist. |
| 7 | GDPR: account deletion and connector tokens (review Finding ①). | `anonymise_user_records` best-effort **revokes each connection at Google** then **deletes the `oauth_connections` rows**. Closes the post-deletion "Auracles retains Drive-read capability" gap; symmetric with the existing GDPR export of connections. |

Folded-in hardening (review Finding ②): `file_id` / `folder_id` are `quote(..., safe="")`-encoded
before interpolation into Drive API URL paths.

## Core principle (unchanged from parent)

> A connected external file may live-mirror into Auracles **only until the artifact is
> published**, and in Phase B that mirror is **display-only** (a thumbnail + drift badge). The
> owned bytes copied at import remain the artifact's canonical content until a Phase C re-sync
> pulls new bytes into a new immutable version.

## Data model changes

Additive Alembic migration on `artifacts` (no existing column altered):

| column | type | null | meaning |
|--------|------|------|---------|
| `source_kind` | `varchar(20)` | **NOT NULL, default `'upload'`** | `upload` \| `google_drive` |
| `source_external_id` | `varchar(256)` | nullable | provider file id (NULL for upload) |
| `source_connection_id` | `uuid` FK `oauth_connections(id)` | nullable | which stored connection (NULL for upload) |
| `source_last_synced_at` | `timestamptz` | nullable | wall-clock of last **byte** copy (import in B; resync in C) |
| `source_synced_revision` | `varchar(64)` | nullable | provider `modifiedTime` **at last byte sync** — the drift baseline |

- `source_last_synced_at` and `source_synced_revision` are set at import and by Phase C resync
  only. **Preview never writes them** (preview pulls no authoritative bytes).
- FK uses `ON DELETE SET NULL` (a connection may be revoked/deleted while the copied artifact
  and its owned bytes live on).
- Backwards-compatible: `alembic upgrade head` sets every existing row to `upload`;
  `downgrade -1` drops the five columns.

Drift baseline vs. thumbnail freshness are **two different comparisons** — do not conflate:
- **Drift badge** = current `modifiedTime` vs `source_synced_revision` (frozen at last byte sync).
- **Thumbnail freshness** = current `modifiedTime` vs the cached preview object's key version
  (tracks the *latest* source state, independent of the baseline).

## Import path change (`from-connector`)

`import_artifact_from_connector` (frameworks/service.py) — after the existing copy-in — stamps:
`source_kind='google_drive'`, `source_external_id=file_id`, `source_connection_id=connection_id`,
`source_last_synced_at=now`, `source_synced_revision=metadata['modifiedTime']`. Requires adding
`modifiedTime` to the `get_drive_file_metadata` `fields` set. Plain upload path stamps
`source_kind='upload'` and leaves the rest NULL.

## Draft live-mirror preview

### Endpoint

`GET /v1/frameworks/{framework_id}/artifacts/{artifact_id}/source-preview`

- **Auth:** framework owner only.
- **Gate:** framework status ∈ `{draft, pipeline_failed, pipeline_passed}` (reuse the
  `_require_editable_artifacts` predicate). Any other status → 409/404.
- **Only** for `source_kind='google_drive'` artifacts; `upload` artifacts → 404 (nothing to
  mirror).
- **Response schema** (dedicated, *not* `ArtifactResponse`):
  ```
  SourcePreviewResponse {
    preview_url: str | null       # presigned GET to our cached thumbnail; null if none available
    source_updated: bool          # current modifiedTime != source_synced_revision
    source_last_synced_at: datetime | null
  }
  ```

### Server flow (per view)

1. Load owned artifact + its `source_connection_id`; obtain a fresh access token via
   `get_active_connection_with_fresh_token(connection_id=...)`.
2. `files.get(fileId, fields="modifiedTime,thumbnailLink")` — cheap metadata call, **every view**.
   (401/403 → `reauth_required` 409; other failure → 502.)
3. `source_updated = current_modifiedTime != artifact.source_synced_revision`.
4. Thumbnail cache: key `frameworks/{fw}/artifacts/{art}/source-preview/{current_modifiedTime}.png`.
   - `object_exists(key)` → hit → presigned GET.
   - miss → **host-allowlist** `thumbnailLink` (`*.googleusercontent.com`, `docs.google.com`) →
     fetch bytes with a **size-cap** (reuse the `download_drive_file` streaming-cap pattern) →
     `upload_bytes(key)` → best-effort `delete_object` of the previous revision's key → presigned GET.
   - Google may not expose a `thumbnailLink` (e.g. very fresh file) → `preview_url = null`.
5. Never write `source_last_synced_at` / `source_synced_revision`.

### Confidentiality (hard invariant)

The source-preview URL and `source_updated` flag are **never** fields on `ArtifactResponse` or
any public/catalog/buyer serializer — they exist only on `SourcePreviewResponse`, produced only
by the owner-only endpoint. Leak is prevented **structurally**, not by a runtime flag.

### At publish

Publishing deletes the artifact's `source-preview/*` S3 objects (transient cache cleanup). The
**binding columns persist** (Phase C resync needs them). Buyers receive the frozen pipeline
thumbnail of the owned, scanned bytes — never the source-preview.

## GDPR (Finding ①)

`anonymise_user_records` (gdpr/anonymise.py), inside the existing tombstone transaction and
beside the current S3-delete-in-txn:

1. Load the user's `oauth_connections`.
2. For each with a stored token: best-effort `revoke_drive_token(decrypt(...))`
   (non-raising, 30 s-bounded — a revoke failure must not block deletion).
3. `delete(OAuthConnection).where(user_id == user_id)` — delete rows, not just null tokens.

Post-deletion: no tokens, no connection rows, and the Google grant actively revoked. Symmetric
with the GDPR export that already lists connections.

## Security

- **Token handling unchanged from Phase A** — Fernet-encrypted at rest, server-side refresh,
  never returned in a response, never logged.
- **SSRF** — the only new external fetch is the thumbnail. `thumbnailLink` comes from a provider
  response, so its host is **allowlisted** before the GET; we never fetch arbitrary user-supplied
  URLs. Size-capped like the download path.
- **No egress of licensed/PII bytes** — the preview is a *thumbnail of the contributor's own
  draft source*, fetched into our infra; nothing is sent to a third party.
- **Access control by construction** — preview is owner-only, pre-publish-only, and lives in a
  schema no buyer/public path constructs.
- **Audit** (`module="frameworks"`) — source binding at import already audits `artifact_uploaded`;
  add nothing new for preview reads (reads of one's own draft thumbnail are not security events).
  GDPR revoke/purge is covered by the existing account-deletion audit trail.

## What Phase B is NOT

- **Not** re-sync / re-bind — pulling changed bytes into a new version is Phase C.
- **Not** a byte-less artifact — every artifact still owns its bytes from import.
- **Not** live-mirror of sold artifacts — permanently out of scope (parent-spec rationale).
- **Not** Dropbox/OneDrive — Google Drive only, provider-generic abstraction preserved.

## Testing (TDD — RED→GREEN per slice)

**Unit (service):**
- Import stamps all five source columns (`google_drive`); plain upload stamps `upload` + NULLs.
- `source_updated` true when current `modifiedTime` ≠ baseline, false when equal.
- Thumbnail cache: hit skips fetch; miss fetches + uploads versioned key + deletes prior key.
- `thumbnailLink` host not in allowlist → refused (no fetch).
- Preview refused for `upload` artifacts and for non-pre-publish statuses.
- `anonymise_user_records` revokes + deletes connections; revoke failure still deletes rows.

**Integration (endpoints):**
- `GET source-preview` as owner on a draft `google_drive` artifact → `preview_url` + flags;
  edit reflected (new `modifiedTime` → `source_updated=true`, new presigned key).
- Non-owner → 403; published artifact → 409/404; `upload` artifact → 404.
- Preview URL/flag **absent** from every `ArtifactResponse` (catalog, buyer library, owner list).
- Account deletion as a connected user → `oauth_connections` rows gone; Google revoke attempted.

**Security:**
- Tokens never in `source-preview` responses or logs.
- Migration `upgrade head` + `downgrade -1` both succeed; existing rows → `upload`.

## Frontend (Next.js)

- Draft artifact card (owner, contributor dashboard): render the source-preview thumbnail via
  `preview_url` and a **"Source updated"** badge when `source_updated`. Owner-only, draft-only.
- Mobile-first, 44 px touch targets, tested at 375 px.
- OpenAPI updated first, frontend client regenerated.

## Risks

- **Drive thumbnail lag** — Google regenerates thumbnails asynchronously, so the *image* can
  trail an edit by seconds/minutes. `modifiedTime` updates instantly, so the **badge stays
  accurate** even when the picture lags. Documented, accepted.
- **Preview object accumulation** — mitigated by deleting the prior revision on refresh and all
  `source-preview/*` at publish; optional S3 lifecycle rule as backstop.
- **Scope creep toward re-sync / live-mirror-of-sold** — guard in review; both are out of scope.
