# Framework Artifact Connectors & Source-of-Truth Model — Design

- **Date:** 2026-06-28 (open questions resolved 2026-07-03)
- **Status:** Approved — Phase A planned first
- **Author:** William Ikeji (architect) + agent
- **Module:** `frameworks` (artifacts)
- **Related FRs:** FR-FWK-* (artifact upload, versioning, publish/review workflow)

## Context

Frameworks are sold as licensed assets. Each Framework owns one or more **Artifacts** —
uploaded binary files (PDF, DOCX, XLSX, PPTX, ZIP, images). Today an artifact's only
source is a direct browser upload to S3, after which it runs the mandatory pipeline
(virus scan → PII detection/redaction → fingerprint → rarity → index) and is frozen into
an immutable per-version snapshot (`FrameworkVersion`).

Two requests prompted this design:

1. **Editing uploaded content** — let contributors keep artifacts current without the full
   manual re-upload dance.
2. **Connectors + live mirror** — let contributors connect Google Drive / Dropbox / OneDrive,
   author in their own tools, and have Auracles reflect changes (the Notion live-embed feel:
   edit at source, reload, see the update).

This document records the decisions reached while stress-testing those ideas, and the
architecture that satisfies the desired ergonomics **without breaking provenance, licensing,
or the security pipeline**.

## The decisions that shaped this

These were resolved during brainstorming and are now locked unless the architect reopens them:

| # | Question | Decision |
|---|----------|----------|
| 1 | Edit binary content in-browser (Apryse/OnlyOffice) vs. native authoring vs. connectors? | **Connectors + contributor's own tools are the source of truth.** In-app editing (Apryse/OnlyOffice) is deferred — optional later, not core. |
| 2 | Lossy parse→markdown→recompile (LlamaParse/Marker + Lexical + python-docx)? | **Rejected** for editing. That stack is AI-ingestion/RAG, not fidelity editing. May reappear only as an optional AI feature, never as the storage round-trip. |
| 3 | Live mirror of a **sold** artifact (buyers always see seller's latest)? | **Rejected.** A licensed transaction needs a fixed thing to have been sold. |
| 4 | Live mirror while **drafting**? | **Allowed.** Nothing is sold yet; pure authoring convenience. |
| 5 | What happens at publish? | **Snapshot.** Bytes are copied into our S3 and run the full pipeline. The sold copy is frozen. |
| 6 | New version: re-sync existing source, or connect a new file? | **Both**, per-artifact. Same version flow, two byte-sources. |

## Core principle: live while drafting, frozen when sold

The single rule the whole design hangs on:

> A connected external file may live-mirror into Auracles **only until the artifact is
> published**. Publishing copies the bytes into our S3, runs the pipeline, and freezes an
> immutable version. After that, the sold copy never changes; updates create a **new version**.

This gives contributors the Notion experience *during authoring* (edit in Drive, reload,
see it) while preserving every marketplace guarantee for buyers.

| Stage | Live mirror from source? | Canonical bytes live in | Pipeline |
|-------|--------------------------|-------------------------|----------|
| Draft / authoring | ✅ Yes — reflect on reload | External (Drive/Dropbox/OneDrive) | not yet |
| Publish | 🔒 Snapshot copy-in | **Our S3** | runs fully, gates publish |
| After purchase | ❌ Frozen | Our S3 (immutable version) | n/a |
| New version | ✅ re-sync or re-bind, then snapshot again | External until next publish | re-runs |

## Connectors

Two distinct capabilities, often conflated. Only one touches sold assets.

### Import connector (copy-in) — core

"Sign in to Drive/Dropbox/OneDrive, pick a file." Auracles copies the **bytes into our S3**
at selection time. From that moment it is a normal owned artifact: same upload path, same
pipeline, same versioning. This is purely a nicer "upload" button and carries no
architectural conflict.

### Live-mirror preview (draft only) — core to the requested UX

While an artifact is in **draft**, the connected source file is mirrored for preview: on
page reload, Auracles fetches the current source bytes (or source-provided preview/thumbnail)
and shows them. This is the "edit in Drive → reload → updated" behaviour. It exists **only**
for unpublished artifacts and is never the storage of record.

> **Implementation note:** "mirror on reload" is a pull, not a live websocket. We re-fetch the
> source on draft view. No background polling of external providers (cost, rate limits,
> token churn). The contributor explicitly drives refresh by reloading / clicking refresh.

### What we are NOT building

- ❌ Live mirror of a **published or sold** artifact.
- ❌ Background/scheduled auto-sync that silently changes a listed framework.
- ❌ In-app binary editing (Apryse/OnlyOffice) in v1.
- ❌ Lossy parse→recompile pipeline.

## Source binding model

Each artifact records where its bytes came from, so a later version can pull again.

```
artifact.source = {
  kind: "upload" | "drive" | "dropbox" | "onedrive",
  external_id: str | null,        # provider file id (null for plain upload)
  connection_id: UUID | null,     # which stored OAuth connection
  last_synced_at: datetime | null,
}
```

- New field(s) on the `artifacts` table → small Alembic migration. No existing column changes.
- OAuth connections (provider tokens) are stored per-user, encrypted at rest, referenced by
  `connection_id`. Tokens are **never** returned in any response or logged.
- Binding is **per-artifact**: a framework with three artifacts can have three different
  sources.

## Version mechanics: re-sync vs. re-bind

A new version supplies fresh bytes. Two ways to get them, chosen per-artifact:

| | Re-sync | Connect new / re-bind |
|---|---------|------------------------|
| What | Reuse stored `source`, pull latest from same file | Point at a different file, switch connector, or plain upload |
| UX | one click "Pull latest" | "Replace source" |
| When | normal update — same doc edited in place | file moved/renamed/deleted, switched tools, or link broke |

Both paths converge: new bytes → new immutable `FrameworkVersion` → pipeline re-runs → old
buyers keep their purchased version → new buyers get the update.

### Edge cases baked in

1. **No-op guard.** Re-sync returning identical bytes must **not** create an empty version.
   Detect via the simhash/minhash we already compute; refuse with "Source unchanged since last
   sync." Prevents version-spam.
2. **Dead link / stale token.** Source file deleted or access revoked → re-sync fails loud and
   prompts **re-bind** (the escape hatch — never let a contributor get stuck because their
   source vanished). Expired OAuth token → prompt re-auth.
3. **Publish gate unchanged.** A version cannot publish until its bytes are in our S3 and have
   passed the pipeline, regardless of source. Connectors change *how bytes arrive*, never
   *whether they are scanned*.

## Security

Connectors add an external-data-fetch surface and OAuth tokens. The mandates:

- **No egress of paid/licensed/PII artifacts to third parties.** Bytes flow source → our S3 →
  buyer (presigned URL). We never send artifacts to a SaaS parser/editor. (This is why
  LlamaParse-as-SaaS and SaaS-hosted editors were rejected.)
- **Pipeline is non-negotiable.** Every byte that becomes a sold artifact passes virus + PII +
  fingerprint + rarity + index in our infra. Live-mirror preview bytes (draft) are *display
  only* and never bypass the pipeline into a sellable state.
- **OAuth tokens** stored encrypted, scoped minimally (read-only file access), never logged,
  never in responses. Token refresh server-side only.
- **SSRF / fetch safety.** Source fetches go only to known provider APIs via their SDKs, never
  to arbitrary user-supplied URLs.
- **Access control intact.** Buyers receive license-checked presigned S3 URLs — not external
  share links. Source sharing settings never govern buyer access.
- **Audit.** Connect, re-sync, re-bind, snapshot-on-publish, and token re-auth are
  security-relevant and written to the audit log (`module="frameworks"`).

### Why live-mirror of sold artifacts is incompatible (rationale, for the record)

Kept here so this isn't relitigated. A sold artifact that stays live-linked to the seller's
Drive breaks: (1) provenance — the bought asset can silently change/vanish; (2) nothing
immutable to license/escrow against; (3) pipeline bypass — unscanned malware/PII served to
buyers, plagiarism undetectable; (4) access control — external share settings, not our
license, govern access, and revocation is impossible; (5) link-rot — seller deletes file →
every buyer 404s; (6) rebroadcast/ToS exposure. Notion's live embed survives none of these
because it is internal and trusted, with no transaction. The marketplace boundary is
adversarial with money in escrow.

## Data model changes

- `artifacts`: add `source_kind`, `source_external_id`, `source_connection_id`,
  `source_last_synced_at`. Alembic migration; additive, backwards-compatible.
- New table `oauth_connections` (or reuse existing OAuth account infra if suitable):
  per-user provider connections, encrypted tokens, scopes, status.
- No changes to `FrameworkVersion` snapshot semantics — connectors feed bytes *into* the
  existing snapshot flow.

## API surface (additive)

- `GET  /v1/integrations/connectors` — list available providers + user's connection status.
- `POST /v1/integrations/connectors/{provider}/connect` — start OAuth (read-only scope).
- `GET  /v1/integrations/connectors/{provider}/callback` — finish OAuth, store connection.
- `DELETE /v1/integrations/connectors/{provider}` — revoke a connection.
- `GET  /v1/integrations/connectors/{provider}/files` — browse/pick source files.
- `POST /v1/frameworks/{id}/artifacts/from-connector` — create artifact bound to a source
  (copy-in for upload-style; bind for draft live-mirror).
- `POST /v1/frameworks/{id}/artifacts/{artifact_id}/resync` — pull latest from stored source
  (used inside a new-version flow).
- Draft preview re-fetch is served through the existing artifact preview path; no new
  public-mirror endpoint.

OpenAPI contract updated first, then frontend client regenerated.

## Phasing

1. **Phase A — Import connectors (copy-in).** Drive/Dropbox/OneDrive OAuth, file pick,
   copy bytes to S3, normal pipeline. Delivers ~80% of the value at lowest risk.
2. **Phase B — Draft live-mirror preview + source binding.** Reflect source on reload for
   unpublished artifacts; persist `source` on the artifact.
3. **Phase C — Re-sync / re-bind new-version flow.** "Pull latest" and "Replace source",
   no-op guard, dead-link handling.
4. **Phase D (optional, later) — In-app editing** (Apryse for PDF+DOCX, or OnlyOffice for full
   Office) editing the owned copy. Only if contributors actually ask for it.

## Testing (TDD)

- Unit: source-binding persistence; re-sync produces new version; no-op guard blocks empty
  version; dead-link → re-bind required; publish gate runs pipeline regardless of source.
- Integration: connector OAuth happy path + revoke; file pick → copy-in → artifact created;
  resync endpoint; draft preview reflects source; published artifact never re-fetches source.
- Security: tokens never in responses/logs; buyer access via presigned URL only; no external
  fetch to arbitrary URLs.

## Open questions — resolved 2026-07-03

- **Provider set for v1:** Google Drive only. Dropbox/OneDrive follow once the pattern is
  proven; the connector abstraction must still be provider-generic.
- **OAuth storage:** new `oauth_connections` table in a new `integrations` module.
  Confirmed against the auth module: `oauth_accounts` is an identity link only
  (`provider` + `provider_id`, no tokens/scopes/status) and its
  `unique(provider, provider_id)` constraint conflicts with connecting a different Google
  account than the login identity. Tokens encrypted with a new per-domain Fernet key
  following the existing `core/config.py` / `core/security.py` pattern
  (`totp_encryption_key` et al.).
- **Draft live-mirror preview:** provider thumbnail (Drive `files.get` → `thumbnailLink`,
  fetched server-side with the stored token). Industry standard (Notion/Slack/Confluence
  all use provider previews); self-render only once we own the bytes, where the pipeline
  already produces thumbnails. Phase B concern — decided now, built later.
- **Plan scope:** Phase A only is planned first; B/C planned after A ships and is reviewed.

## Deferred

- In-app editing SDK choice (Apryse vs. OnlyOffice) — only if/when Phase D is approved; carries
  a cost decision.

## Risks

- **New external dependencies (OAuth providers).** Justified: connectors are the requested
  feature and reuse our existing S3/pipeline; minimal new attack surface if tokens are scoped
  read-only and bytes always land in our pipeline.
- **Token security.** Encrypted at rest, never logged, server-side refresh — must be enforced
  in review.
- **Scope creep toward live-mirror-of-sold.** Explicitly out of scope; guard against it in
  review.
