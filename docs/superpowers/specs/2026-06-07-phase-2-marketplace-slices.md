# Phase 2 — Core Marketplace: Sliced Build Plan

**Status:** Draft — awaiting human approval before Slice 1 starts.
**Maps to:** FR-EXP-001..011, FR-FWK-001..014 (reviews schema only — flow deferred to Phase 3), BR-EXP-001..003, BR-FWK-001..006, TDD §3 (schema, w/ deltas), TDD §7 (search), TDD §8 (RBAC).
**Depends on:** Phase 1 (Auth + KYC + RBAC + audit log).

---

## Context

Phase 1 (auth, identity, KYC, RBAC, audit) ships. Phase 2 builds the marketplace surface — Contributors create + version Frameworks, upload Artifacts, watch them flow through a 9-step processing pipeline (virus scan → extract → PII → metadata → MinHash → internal rarity → external rarity → thumbnail → search index), and click **Publish** once every gate is green. Operators browse the public catalog (SSR + faceted filter + full-text search), view Framework detail pages, and once they hold a license (purchase flow lands Phase 3) can download Artifacts through KYC-gated presigned URLs.

Sliced into **12 small, independently reviewable adds** so the human keeps pace and commits between slices. One commit per slice. No autonomous next slice.

---

## Coverage matrix

| ID | Title | Slice |
|----|-------|------|
| FR-EXP-001 | Paginated catalog (20/pg default) | 10 |
| FR-EXP-002 | Sort: newest / top-rated / most purchased / price | 10 (top-rated + most-purchased shimmed `0` until Phase 3) |
| FR-EXP-003 | Full-text search (title, description, tags) | 10 |
| FR-EXP-004 | Faceted filters (sector, industry, function, ...) | 10 |
| FR-EXP-005 | Framework card payload | 10 + 12 |
| FR-EXP-006 | Framework detail page | 10 + 12 |
| FR-EXP-007 | Preview artifact on detail page | 10 (gating) + 12 (UI) |
| FR-EXP-008 | Unauthenticated browse, auth prompt on action | 10 + 12 |
| FR-EXP-009 | Related frameworks (6) | 10 (baseline: tag/category overlap; embedding upgrade deferred) |
| FR-EXP-010 | Watchlist | **DEFERRED → Phase 5 Collections** |
| FR-EXP-011 | "Owned" badge in place of purchase CTA | 11 + 12 |
| FR-FWK-001 | Contributor creates Framework w/ full metadata | 2 |
| FR-FWK-002 | Contributor uploads Artifacts (PDF/DOCX/XLSX/PPTX/ZIP, 500MB total) | 3 |
| FR-FWK-003 | Pricing + license type + commercial rights config | 2 |
| FR-FWK-004 | Designate preview Artifact | 2 |
| FR-FWK-005 | Save Framework as `draft` | 2 |
| FR-FWK-006 | Submit for review | 9 (deviation: pipeline-gate, not admin) |
| FR-FWK-007 | Review outcome notification | 9 (deviation: outcome = pipeline result, surfaced to Contributor) |
| FR-FWK-008 | Create new version of published Framework | 8 |
| FR-FWK-009 | Unpublish | 8 |
| FR-FWK-010 | Per-framework Contributor analytics | 12 (views + purchase + revenue + avg-review; latter three shimmed `0` until Phase 3) |
| FR-FWK-011 | Operator library | 11 + 12 |
| FR-FWK-012 | Operator downloads Artifacts | 11 |
| FR-FWK-013 | New-version notification to licensees | 8 (Celery task; UI surface in Phase 5 settings) |
| FR-FWK-014 | Operator submits Review (1–5 + body) | **schema in Slice 1; flow DEFERRED → Phase 3** (BR-FWK-004 requires active license) |
| BR-EXP-001 | Only `published` frameworks in catalog | 10 |
| BR-EXP-002 | Contributor's own frameworks excluded from their Explore | 10 |
| BR-EXP-003 | Search + filter results < 2s under normal load | 10 (GIN index + EXPLAIN ANALYZE in tests) |
| BR-FWK-001 | Framework needs ≥1 Artifact before submission | 9 |
| BR-FWK-002 | Framework price > 0 | 2 |
| BR-FWK-003 | Artifact change on published Framework → version bump required | 8 |
| BR-FWK-004 | Operator can only review Framework they license | **Phase 3** |
| BR-FWK-005 | One review per Operator per Framework; 30d edit window | **Phase 3** |
| BR-FWK-006 | Artifact downloads logged per license for audit | 11 |

---

## Approved FRD / TDD deviations (Phase 2)

| Ref | Spec says | Plan does | Reason | Approved |
|-----|-----------|-----------|--------|----------|
| FR-FWK-006 / FR-FWK-007 | Admin reviews `submitted` framework → approves/rejects | Pipeline acts as gate. Contributor submits → pipeline runs → on pass, Contributor sees green checks + **Publish** button + publishes themselves. On fail, Contributor sees per-check reasons (virus / PII / internal duplicate / KYC) + fixes + re-submits. Admin role flips to **post-publish moderation** — admin can `suspend` published frameworks on abuse report or spot-check; existing licensees retain access. | Removes admin bottleneck; Contributor UX is faster; trust signal preserved by pipeline checks + post-publish moderation. | Human, 2026-06-07 |
| TDD §3 `artifact_fingerprints.embedding vector(1536)` | pgvector semantic embedding | **Dropped.** Replaced with `minhash_signature BYTEA`, `simhash BIGINT`, `metadata_vector JSONB`. pgvector dep removed from Phase 2. | MinHash + LSH is industry standard for near-duplicate detection (Google web dedup, GitHub clone detection, LLM training data dedup). Cheaper, explainable, deterministic, fits the actual abuse case (lift-and-rename), no model load. Embeddings can re-enter Phase 5 only if paraphrase-only theft is observed in production. | Human, 2026-06-07 |
| TDD §3 `artifacts.rarity_score NUMERIC(5,4)` (single column) | One score | Split into `internal_rarity NUMERIC(5,4)`, `external_rarity NUMERIC(5,4)` (nullable — null if Stage B skipped or degraded), and blended `rarity_score NUMERIC(5,4)` (`0.5*internal + 0.4*external + 0.1*metadata_uplift`). | Internal vs external are different signals; storing both lets us re-blend without re-processing. Audit clarity. | Human, 2026-06-07 |
| TDD §3 new table | n/a | New `artifact_rarity_audit` table: every input to the rarity score is logged (max internal Jaccard + nearest_match_id, external phrases queried + hit counts, metadata uplift breakdown, final blend, timestamp). | Explainability to Contributor + admin re-score capability if heuristics evolve. | Human, 2026-06-07 |
| FR-EXP-009 | Up to 6 related frameworks recommendations | Phase 2 ships tag + category overlap baseline. Embedding-based recommendation deferred to Phase 5 (only if baseline feels weak in production). | YAGNI — baseline is good enough for catalog-launch traffic; defer ML upgrade until evidence. | Human, 2026-06-07 |
| FR-EXP-010 | Watchlist | **Deferred** to Phase 5 Collections module (FR-COL-*). | Scope; watchlist UX overlaps Collections. | Human, 2026-06-07 |
| BR-AUTH-002 / Phase 1 KYC scope | KYC gates publish + upload + payout (Contributor) + download (Operator) | **Tightened**: KYC also gates `POST /v1/frameworks` (Contributor create), not only upload/publish. | Prevents drafts that cannot be published; prevents PII/abuse loads from non-verified Contributors hitting the platform; aligns w/ team-lead "incomplete users may only browse + preview" rule. | Human (team-lead), 2026-06-07 |
| FR-EXP-007 | Preview artifact on detail page | **Public, no auth/license/KYC.** Delivered via `preview_url` field on detail response (presigned GET, 15min TTL, 60/min/IP rate limit). Designated preview artifact only — never any other artifact. | SEO + frictionless discovery; preview is a marketing surface, not a paid surface. | Human, 2026-06-07 |

---

## Architectural decisions

| Decision | Value | Note |
|----------|-------|------|
| Text extraction | `pdfplumber` for PDF + built-in Office Open XML text fallback; optional `unstructured` hook if installed in worker image | Avoids Python 3.13 `llvmlite`/CMake build instability from the full `unstructured` stack while keeping an upgrade path. |
| PII detection | Microsoft Presidio (`presidio-analyzer` + `presidio-anonymizer`) + spaCy `en_core_web_lg` | Apache 2.0. Local, free, confidence scores per detection drive `pii_review_needed` threshold. Anonymizer produces `clean_file_key` redacted copy. |
| Metadata vector | scikit-learn `TfidfVectorizer` + custom counters (char_count, word_count, n_headings, n_tables, n_images, top-20 tf-idf terms, language, tag overlap count) | Stored as JSONB. Drives metadata uplift (small fraction of rarity blend) + recommendation tag overlap. |
| Near-duplicate detection | MinHash via `datasketch` (MIT), with Redis LSH indexing deferred to Slice 9 publish/unpublish wiring | 128 permutations, 5-word shingles, deterministic signature. SimHash 64-bit pre-filter stored for the future LSH/query speed path. |
| Internal rarity | `1 - max_jaccard_to_any_existing_published_artifact` | Slice 5 computes against DB-backed published artifact signatures. Slice 9 inserts/removes published artifacts into a Redis-backed LSH index for sub-linear lookup once publish/unpublish state transitions exist. |
| External rarity | **Brave Search API** (independent index, GDPR-friendly, free 2k/mo dev tier, ~$5/1k after) | Stage B; gated by `internal_rarity > 0.7` so we only pay when content is internally rare. 8 top-tf-idf phrase queries, quoted. Phrase-level Redis cache (30d TTL) so popular phrases dedupe across uploads. Graceful degrade: if Brave returns error/timeout → set `external_rarity = NULL`, surface "external check unavailable" badge in Contributor pipeline status, do not block publish. |
| External rarity gate | **Soft-fail w/ acknowledgement** | When `external_rarity < 0.3`, Contributor sees "this content appears widely available online (X web matches). I confirm this is my original work or properly licensed → publish." Acknowledgement timestamp + IP audited. Hard block reserved for virus + internal duplicate + KYC. |
| Thumbnail | `pdf2image` (Poppler) + Pillow | First page of preview artifact (or first PDF/image artifact) → 400×600 PNG, stored at `s3://auracles-thumbnails-{env}/{framework_id}.png`. |
| Search | Postgres FTS — `to_tsvector('english', title || description || coalesce(tags_text, ''))` + GIN index | TDD §7 confirmed. Migrate to Meilisearch in Phase 5 only if catalog grows past ~50k frameworks. |
| Versioning UX | Contributor picks change type via 3-radio (`fix` / `improvement` / `major`). Platform auto-computes semver (`1.2.0 → 1.2.1` / `1.3.0` / `2.0.0`). Stored as `version VARCHAR(20)` per TDD. Prior version always displayed in modal. `change_log` textarea required. Artifact inheritance is per-file checkbox. | No typing → no stress, no format errors, no forgotten prior. |
| License types | `single_user`, `team` (10 seats max), `enterprise` (admin-mediated, custom invoice, manual seat ceiling) | Subscription/perpetual deferred to Phase 3 / 5. |
| Review state machine | `draft → submitted → processing → {pipeline_passed | pipeline_failed} → published → (Contributor) unpublished | (Admin) suspended` | Single `framework_status` column carries it. Pipeline result fields on `frameworks` row drive the publish button. |
| Admin role | **Post-publish moderation only**: `suspend` published frameworks on abuse report or spot-check; existing licensees keep access. Plus enterprise license grant + admin-mediated invoice. | No admin-gated submission. |
| Reviews | Schema in Slice 1, flow Phase 3 | BR-FWK-004 ties reviews to active licenses; licenses require purchase (Phase 3). |
| Artifact upload | S3 presigned POST, mime + max-size enforced in the POST policy; per-framework 500MB total tracked in service | TDD §10 (artifact bucket private). |
| Download | S3 presigned GET (15m TTL) issued only after RBAC + license check + Operator-KYC check; row written to `artifact_downloads` per BR-FWK-006 | Audit table powers Contributor download counts. |

---

## Cross-cutting concerns (apply to every slice)

1. **Pydantic schemas** on every input. No raw dict.
2. **Loguru bound context** (`module`, `action`, `user_id`, `framework_id`, `artifact_id`, `task_id`, `request_id`) on every log line. Per CLAUDE.md logging table.
3. **Audit DB write** on: `framework_created`, `framework_submitted`, `framework_pipeline_passed`, `framework_pipeline_failed`, `framework_published`, `framework_unpublished`, `framework_suspended`, `framework_version_bumped`, `artifact_uploaded`, `artifact_scan_complete`, `artifact_processing_complete`, `artifact_pii_flagged`, `artifact_rarity_flagged`, `artifact_downloaded`, `license_granted`, `soft_fail_acknowledged`.
4. **`contracts/openapi.yaml` updated in each backend slice.** Slice 12 only ships the FE codegen + UI. Phase 1 finding #8 applies.
5. **KYC enforcement via Phase 1 `require_kyc_verified()` dep:**
   - Contributor side: applied on `POST /v1/frameworks` (create), `POST /v1/frameworks/{id}/artifacts` (upload), `POST /v1/frameworks/{id}/publish`, `POST /v1/frameworks/{id}/versions` (new version).
   - Operator side: applied on `GET /v1/frameworks/{id}/artifacts/{aid}/download`.
   - **`kyc_status='pending'` is NOT verified.** Pending = KYC submitted, awaiting admin review. Treated identically to `unverified` for action gates; only `verified` passes the dep.

6. **Incomplete-user rule (Phase 1 carry-over, explicit for Phase 2).** Email-unverified people cannot authenticate in Phase 1, so they browse + preview as unauthenticated visitors until email verification is complete. An "incomplete authenticated user" = authenticated AND any of: blank `display_name`, no role assigned, `kyc_status != 'verified'`. Incomplete authenticated users:
   - **Can:** browse catalog (`GET /v1/explore/frameworks`), search, filter, view detail page, view preview artifact (FR-EXP-007 is public by design — see concern 7), see "Owned" badge logic resolving to false.
   - **Cannot:** create framework, upload artifact, submit, publish, version-bump, download licensed artifacts, grant license, suspend.
   - **UX:** any 403 from an action gate returns `{ error_code: "kyc_required" | "profile_required" | "role_required", onboarding_url: "/settings/onboarding" }`. FE intercepts → routes to `/settings/onboarding` per Phase 1 Slice 10 pattern. Email verification failures stay in the Phase 1 auth flow, not marketplace action gates.
   - **Explicit Phase 2 product rule:** Contributor create is gated by `require_kyc_verified()` *before* any artifact is uploaded. This is intentional, not over-gating — prevents Contributors creating drafts they cannot publish, and prevents PII / abuse uploads bypassing the marketplace's KYC trust floor.

7. **Preview artifact delivery is public.** FR-EXP-007 designed for SEO + frictionless discovery. Implementation: detail-page response payload includes `preview_url: string | null` field — a presigned GET URL for the framework's designated preview artifact, valid 15 min, regenerated per request, **no auth + no license + no KYC required**. Only the artifact explicitly designated via `PATCH /v1/frameworks/{id}/preview-artifact` (FR-FWK-004) is exposed this way; all non-preview artifacts remain gated through the licensed-download path in Slice 11. Preview-artifact S3 keys may be served from a separate `auracles-previews-{env}` prefix to make bucket policy explicit. Rate limit: 60 preview requests/min per IP via Redis fixed-window — guards against bulk-scrape.
8. **Transactions.** Any write touching 2+ tables uses `async with db.begin()`. Examples: framework publish (update `frameworks.status` + insert `framework_versions` row); license grant (insert `licenses` + insert `audit_logs`); download (insert `artifact_downloads` + emit Celery task for Contributor view-count).
9. **Celery task idempotency.** `process_artifact(artifact_id)` is the orchestrator; it must be safe to retry from any step (each sub-step writes its own state column on `artifacts` and checks before re-running). All sub-tasks `bind=True` w/ `self.retry(exc=exc, countdown=60)` on transient.
10. **No secret in logs.** Never log S3 presigned URLs (log `artifact_id` only), Brave API key, KYC document paths.
11. **Mobile-first per Brand Book §11–13.** All FE in Slice 12 mobile-first; touch targets ≥44px; no horizontal-scroll tables on mobile.

---

## Slice plan

Each slice ends green: `ruff` + `mypy --strict` + `pytest --cov` (≥80% on touched modules) + Alembic `upgrade head` and `downgrade -1` both succeed. **One commit per slice.** Human reviews + commits before next slice starts.

---

### Slice 1 — Schema foundation
**Add (migration `backend/migrations/versions/2026_06_XX_frameworks_artifacts_and_pipeline.py`):**
- Enums: `framework_status_enum` (`draft`, `submitted`, `processing`, `pipeline_passed`, `pipeline_failed`, `published`, `unpublished`, `suspended`), `scan_status_enum` (`pending`, `clean`, `infected`, `error`), `processing_status_enum` (`pending`, `processing`, `processed`, `failed`, `flagged_pii`, `flagged_rarity`), `org_size_enum` per TDD §3, `license_type_enum` (`single_user`, `team`, `enterprise`), `license_status_enum`, `change_type_enum` (`fix`, `improvement`, `major`), `version_action_enum`.
- `frameworks` table per TDD §3 + columns: `change_type` (last bump's reason), `last_pipeline_run_at`, `pipeline_failure_reasons JSONB`.
- `framework_versions` table per TDD §3 + `change_type change_type_enum NOT NULL`, `change_log TEXT NOT NULL`.
- `artifacts` table per TDD §3 **with schema deltas**:
  - drop `embedding` reference
  - add `minhash_signature BYTEA`, `simhash BIGINT`, `metadata_vector JSONB`
  - split `rarity_score` → `internal_rarity NUMERIC(5,4)`, `external_rarity NUMERIC(5,4) NULL`, `rarity_score NUMERIC(5,4)`
- `artifact_pii_audit` table per TDD §3.
- **New** `artifact_rarity_audit` table: `id`, `artifact_id`, `internal_jaccard NUMERIC(5,4)`, `nearest_match_id UUID`, `external_phrases_queried TEXT[]`, `external_hit_counts INTEGER[]`, `metadata_uplift NUMERIC(5,4)`, `blended_score NUMERIC(5,4)`, `soft_fail_acknowledged BOOLEAN`, `acknowledged_at TIMESTAMPTZ`, `acknowledged_ip INET`, `created_at`.
- `licenses` table per TDD §3 (schema only — write path Slice 11).
- `artifact_downloads` table per TDD §3 (write path Slice 11).
- `reviews` table per TDD §3 (schema only — flow Phase 3): `id`, `framework_id`, `operator_id`, `license_id`, `score SMALLINT CHECK BETWEEN 1 AND 5`, `body TEXT`, `created_at`, `updated_at`, `UNIQUE(framework_id, operator_id)`.
- Indexes per TDD §7: `idx_frameworks_status`, `idx_frameworks_contributor`, `idx_frameworks_category`, `idx_frameworks_sector`, `idx_frameworks_price`, GIN `idx_frameworks_search` on tsvector, GIN `idx_frameworks_tags` on `tags`. Plus `idx_artifacts_framework`, `idx_artifacts_processing_status`, `idx_artifacts_simhash` (BIGINT btree for pre-filter), `idx_artifact_downloads_license`.

**SQLAlchemy ORM:** `app/modules/frameworks/models.py`, `app/modules/frameworks/models_artifact.py`, `app/shared/models/audit_log.py` extension if needed.

**Test (`tests/unit/test_frameworks_migrations.py`):**
- `upgrade head` → assert tables + enums + indexes exist.
- `downgrade -1` → clean.
- pgvector NOT installed (negative assert — confirms deviation).

**Deps added:** none yet (alembic from Phase 1).

---

### Slice 2 — Framework CRUD (draft state)
**Add:**
- `app/modules/frameworks/schemas.py`: `FrameworkCreate`, `FrameworkUpdate`, `FrameworkResponse`, `FrameworkListItem`, `PricingConfig`. Pydantic validators: `price > 0` (BR-FWK-002), `license_types` non-empty, semver string format on read-side only.
- `app/modules/frameworks/service.py`: `create_framework`, `update_framework` (only `draft` editable on metadata), `get_framework_for_contributor`, `list_contributor_frameworks`, `delete_draft`.
- `app/modules/frameworks/router.py`: `POST /v1/frameworks`, `PATCH /v1/frameworks/{id}`, `GET /v1/frameworks/{id}` (Contributor scope), `GET /v1/frameworks` (Contributor scope; flag in router for catalog access path which lands Slice 10), `DELETE /v1/frameworks/{id}` (draft only).
- Wire `require_role("contributor")` + `require_kyc_verified()` on create + update.

**OpenAPI:** `contracts/openapi.yaml` updated.

**Edge cases tested:**
- Non-contributor creates → 403.
- KYC-unverified contributor creates → 403 + `error_code="kyc_required"` + `onboarding_url="/settings/onboarding"`.
- **KYC pending contributor creates → 403 + `error_code="kyc_required"`** (pending ≠ verified — explicit test).
- Email-unverified visitor clicks Create Framework → login/verify-email flow, no marketplace draft is created.
- Price ≤ 0 → 422.
- Empty `license_types` → 422.
- Update on `submitted`/`published` framework → 409.
- Delete on `published` → 409.

---

### Slice 3 — Artifact upload + S3 + virus scan
**Add:**
- Service: `request_artifact_upload_url(framework_id, filename, mime, size)` returns presigned POST target w/ size + mime conditions; `confirm_artifact_upload(artifact_id)` writes row to `artifacts`, dispatches `scan_artifact` Celery task; `delete_artifact` (draft only).
- Validate: mime in `{application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/vnd.openxmlformats-officedocument.presentationml.presentation, application/zip}`; total per-framework size ≤ 500MB (FR-FWK-002).
- Router: `POST /v1/frameworks/{id}/artifacts/upload-url`, `POST /v1/frameworks/{id}/artifacts/confirm`, `GET /v1/frameworks/{id}/artifacts`, `DELETE /v1/frameworks/{id}/artifacts/{aid}`, `PATCH /v1/frameworks/{id}/preview-artifact` (FR-FWK-004).
- `app/workers/tasks/artifacts.py`: `scan_artifact(artifact_id)` runs ClamAV (`clamdscan`) against S3 object → updates `scan_status`. On `clean`, dispatches `process_artifact`. On `infected`, sets `processing_status='failed'`, writes audit row, dispatches no further. On `error`, retries.
- Dockerfile: worker image includes ClamAV daemon.

**OpenAPI updated.**

**Edge cases tested:**
- Wrong mime → 415.
- Size > 500MB cumulative → 413.
- Upload-url called by non-owner → 403.
- Infected file → `scan_status=infected`, no further processing, Contributor sees red badge.
- Confirm called twice for same artifact → idempotent (200, no duplicate row).
- ClamAV down → task retries up to 5 times then sets `scan_status=error`, alerts admin.

**Deps added:** `boto3` (already in Phase 1 Slice 8), `clamd` (ClamAV Python client).

---

### Slice 4 — Pipeline step 1+2: extract + PII
**Add:**
- `app/workers/tasks/processing/extract.py`: `extract_text(artifact_id)` — `pdfplumber` for PDF tables + built-in Office Open XML fallback, with optional `unstructured.partition.auto` hook when installed. ZIP artifacts are treated as containers: entries are path-validated, symlinks rejected, max file count / uncompressed-size limits enforced, and supported inner files (`PDF|DOCX|XLSX|PPTX|ZIP` up to depth 1) are extracted into one combined metadata payload. Returns text + heading list + table count + word count + archive counts; persists to `artifacts.metadata_vector` (partial).
- `app/workers/tasks/processing/pii.py`: `detect_pii(artifact_id)` — Presidio analyze (`en_core_web_lg`) → list of `{entity_type, score, start, end}`. Confidence threshold: `score ≥ 0.6` → `pii_detected=true`; any finding → `pii_review_needed=true` and `processing_status='flagged_pii'` until a format-preserving redaction path exists. Writes `artifact_pii_audit` row.
- Orchestrator `process_artifact(artifact_id)` delegates to `app/workers/tasks/processing/orchestrator.py`, which runs the currently implemented steps (`extract` then `pii`) in order. Later slices extend this orchestrator with metadata, MinHash, rarity, thumbnail, and search steps.

**OpenAPI:** no new endpoints; processing status read by GET framework already in Slice 2.

**Edge cases tested:**
- Unsupported / corrupt PDF → step 1 sets `processing_status='failed'`, reason captured.
- ZIP with supported inner files → supported files extracted, unsupported files counted, no unsafe paths written to disk.
- ZIP path traversal / symlink / archive bomb risk → extraction fails and writes audit reason.
- All-image PDF → text empty, `pii_detected=false` (defensible), metadata captures `n_images>0`.
- High-confidence PII (NAME, EMAIL, PHONE) → `pii_detected=true`, no `clean_file_key`, blocked for review.
- Low-confidence detection → `pii_review_needed=true` flagged, blocks publish until Contributor resolves it.
- Re-run of `extract` on an already-extracted artifact → idempotent (writes new metadata, doesn't duplicate).

**Deps added:** `pdfplumber`, `presidio-analyzer`, `presidio-anonymizer`, `spacy`, `en_core_web_lg` model (downloaded in worker Dockerfile). `unstructured` remains an optional runtime hook; it was not added to the lockfile because its Python 3.13 dependency chain attempted to build `llvmlite` locally and required CMake.

---

### Slice 5 — Pipeline step 3+4+5: metadata + MinHash + internal rarity
**Add:**
- `app/workers/tasks/processing/metadata.py`: completes `metadata_vector` JSONB → adds `top_tfidf_terms[20]` (via `sklearn.feature_extraction.text.TfidfVectorizer` on extracted artifact text), `language` (via `langdetect`), text/heading/table/image counters, and Framework tag overlap counts.
- `app/workers/tasks/processing/minhash.py`: `compute_minhash(artifact_id)` → 5-word shingles, 128 permutations via `datasketch.MinHash`; persists `minhash_signature BYTEA` (1KB) + `simhash BIGINT` (64-bit pre-filter via `datasketch.LeanMinHash` or roll-your-own simhash).
- `app/workers/tasks/processing/rarity_internal.py`: `compute_internal_rarity(artifact_id)` → compare the current MinHash against **published artifacts only** from the database; compute `max_jaccard` → `internal_rarity = 1 - max_jaccard`; persist + write `artifact_rarity_audit` row (internal section). On publish (Slice 9), artifact is inserted into Redis LSH so this DB-backed comparison can be swapped to sub-linear lookup.

**Edge cases tested:**
- Empty text → `internal_rarity = 1.0` (no comparison possible — defensible: no duplicate to find).
- Single-shingle text (tiny doc) → MinHash defined but low confidence; flag with badge.
- Catalog empty → `internal_rarity = 1.0` for first ever upload.
- Re-run of pipeline → idempotent: signature recomputed, audit row replaces prior on same `artifact_id`.

**Deps added:** `datasketch`, `scikit-learn`, `langdetect`, `joblib`.

---

### Slice 6 — Pipeline step 6: external rarity (Brave Search)
**Add:**
- `app/integrations/brave_search.py`: thin async client. Env vars: `BRAVE_SEARCH_API_KEY`, `BRAVE_SEARCH_BASE_URL` (default `https://api.search.brave.com/res/v1/web/search`). Returns `{ total_hits, query, results: [...] }`. Includes 15s timeout, exponential backoff retry (3 attempts), Redis-cached per `sha256(phrase)` w/ 30d TTL.
- `app/workers/tasks/processing/rarity_external.py`: `compute_external_rarity(artifact_id)`. Gating: skips if `internal_rarity < 0.7` (writes `external_rarity = NULL`, notes "skipped: internally duplicate"). Else picks top-8 phrases from `metadata_vector.top_tfidf_terms` joined as 5-10 word n-grams (selected from extracted text where tf-idf terms co-occur). Queries Brave w/ quoted phrases. Aggregates hit counts → maps via piecewise log function to `external_rarity ∈ [0, 1]`. Writes audit row update.
- Graceful degrade: Brave 5xx / timeout → set `external_rarity = NULL`, set `pipeline_failure_reasons += {"external_check": "unavailable"}` flag in `frameworks`, do not block publish path.

**Edge cases tested:**
- All 8 phrases cache-hit → 0 API calls.
- Brave returns 429 → exponential backoff; if exhausted → degrade gracefully.
- Internal duplicate (`internal_rarity < 0.7`) → Brave skipped (cost guard verified).
- Network down → `external_rarity = NULL`, Contributor sees "external check unavailable" badge.
- Audit row captures every phrase + hit count → re-blendable later.

**Deps added:** `httpx` (already in Phase 1 tests, promote to runtime).

---

### Slice 7 — Pipeline step 7+8+9: blend + thumbnail + tsvector index
**Add:**
- `app/workers/tasks/processing/blend.py`: `compute_final_rarity(artifact_id)` → reads `internal_rarity`, `external_rarity` (or `NULL`), `metadata_uplift` (computed here: bonus if (sector, jurisdiction, category) combo appears < N times in catalog → small additive); writes `rarity_score = 0.5*internal + 0.4*external + 0.1*metadata_uplift` w/ `external_rarity=NULL` re-weights to `0.625*internal + 0.125*metadata_uplift + 0.25*NULL_handled_as_neutral_0.5`. Persists + finalizes audit row.
- `app/workers/tasks/processing/thumbnail.py`: `make_thumbnail(framework_id)` → picks preview artifact (FR-FWK-004) else first PDF/image artifact → `pdf2image.convert_from_path` first page → Pillow resize 400×600 → S3 upload to `auracles-thumbnails-{env}/{framework_id}.png` → store key on `frameworks.thumbnail_key`.
- `app/workers/tasks/processing/search_index.py`: `refresh_framework_tsvector(framework_id)` → updates the tsvector via SQL (`UPDATE frameworks SET tsvector = to_tsvector('english', title || ' ' || description || ' ' || array_to_string(tags, ' '))`). Run on publish (Slice 9) and on metadata update of published framework.
- Final orchestrator action: when all sub-tasks done w/o failure → set `frameworks.status = 'pipeline_passed'`. On any sub-task failure → `frameworks.status = 'pipeline_failed'` + populate `pipeline_failure_reasons JSONB` with per-step result.

**Edge cases tested:**
- Thumbnail with no PDF/image artifact → defaults to generic Brand-Blue framework-type icon (stored once, all such frameworks share the key).
- Blend when `external_rarity = NULL` → re-weighting verified.
- Tsvector contains tags → search by tag matches.
- Re-run of pipeline (e.g. version bump) → tsvector replaced atomically, thumbnail overwritten.

**Deps added:** `pdf2image`, `pillow`. Poppler in worker Dockerfile.

---

### Slice 8 — Versioning + framework state machine extensions
**Add:**
- Service: `create_new_version(framework_id, change_type, change_log, artifact_inheritance)`. Computes new semver: read current `frameworks.version` (or last `framework_versions.version`), apply bump (`fix=patch`, `improvement=minor`, `major=major`). Validates BR-FWK-003 (new version required if any artifact changed). Clones non-inherited artifacts (S3 copy + new `artifacts` rows w/ `processing_status=pending` to re-run pipeline). Sets framework `status=draft` (new version starts as new draft). Returns new draft.
- Service: `unpublish_framework(framework_id)` (FR-FWK-009) → sets `status=unpublished`. Existing licensees keep download access (BR check on download stays license-status, not framework-status).
- Service: `notify_licensees_of_new_version(framework_id, new_version)` Celery task — fires on publish of a non-1.0.0 version. Looks up active licensees (will be empty until Phase 3 ships purchases) — call lands, but list is empty; idempotent. Notification template: `send_new_version_email`.
- Router: `POST /v1/frameworks/{id}/versions` (body: `{change_type, change_log, artifact_inheritance: {artifact_id: bool}}`), `POST /v1/frameworks/{id}/unpublish`.
- Schema updates: `framework_versions.version` is the source-of-truth history. `frameworks.version` points to latest published version's semver string. Prior version snapshot stored in `framework_versions` w/ FK to its artifacts via a join table `framework_version_artifacts` (added in this slice) so prior licensees can still download the exact files they paid for.
- New table `framework_version_artifacts`: `framework_version_id`, `artifact_id`, `is_preview` (PRIMARY KEY composite).

**Edge cases tested:**
- Create new version when no artifact changed + no metadata changed → 422 ("nothing to bump").
- Major bump after `0.0.0` start (initial) → version `1.0.0` (not `0.0.0 → 1.0.0` weirdness — first publish is always `1.0.0`).
- Inherit all artifacts → new draft has same artifacts (no S3 copy, FK only).
- Inherit none → all artifacts cloned to new keys, pipeline reruns.
- Unpublish then publish-new-version → existing licensees notified for new version; new purchases blocked between unpublish + new publish (catalog hides framework while `unpublished`).

---

### Slice 9 — Pipeline-as-gate + Contributor publish + admin suspend
**Add:**
- Service: `submit_framework(framework_id)` (FR-FWK-006): validates BR-FWK-001 (≥1 artifact), KYC verified (BR-AUTH-002), price > 0 (BR-FWK-002). Sets `status=submitted`. Dispatches `process_artifact` chain for each unprocessed artifact. As each artifact completes, last-one-in triggers framework-level decision: if every artifact's `processing_status` ∈ {`processed`} AND none has `pii_review_needed=true` (unaccepted) AND `internal_rarity ≥ 0.3` → `status=pipeline_passed`. Else → `status=pipeline_failed` w/ aggregated `pipeline_failure_reasons`.
- Service: `acknowledge_soft_fail(framework_id)` → Contributor confirms "original work" for external-rarity soft-fail. Writes `artifact_rarity_audit.soft_fail_acknowledged=true` + IP + timestamp. Does **not** publish.
- Service: `accept_redacted_artifact(artifact_id)` → Contributor accepts the Presidio-redacted `clean_file_key` as the canonical artifact (drops the original from S3). Clears `pii_review_needed`. Re-runs pipeline downstream from PII step.
- Service: `publish_framework(framework_id)` (FR-FWK-007 deviation): asserts `status=pipeline_passed`. Inserts artifacts into MinHash LSH index (so future uploads see this in the corpus). Writes `framework_versions` row w/ current semver + change_type + change_log. Sets `frameworks.status=published`, `published_at=now()`. Refreshes tsvector. Dispatches `notify_licensees_of_new_version` Celery task.
- Service: `suspend_framework(framework_id, admin_id, reason)` (admin-only, post-publish). Sets `status=suspended`. Removes from LSH index. Audit row.
- Router: `POST /v1/frameworks/{id}/submit`, `POST /v1/frameworks/{id}/acknowledge-soft-fail`, `POST /v1/frameworks/{id}/artifacts/{aid}/accept-redaction`, `POST /v1/frameworks/{id}/publish`, `POST /v1/admin/frameworks/{id}/suspend`.

**Edge cases tested:**
- Submit w/ 0 artifacts → 422 (BR-FWK-001).
- Submit by KYC-unverified Contributor → 403 + `error_code="kyc_required"`.
- **Submit by KYC-pending Contributor → 403 + `error_code="kyc_required"`** (pending ≠ verified).
- Publish by KYC-pending Contributor (post pipeline pass) → 403 + `error_code="kyc_required"`.
- Submit → all checks pass → `pipeline_passed` → Contributor sees green panel + Publish enabled.
- Submit → infected artifact → hard fail; Contributor cannot acknowledge.
- Submit → high-confidence PII detected → `pii_review_needed=false` (auto-redacted) → passes; or → `pii_review_needed=true` → blocked until Contributor accepts.
- Submit → `internal_rarity < 0.3` → hard fail; Contributor sees nearest-match link.
- Submit → `external_rarity < 0.3` → Publish remains disabled until `acknowledge_soft_fail` called.
- Submit → Brave unavailable → soft-fail acknowledgement still required (uses internal as proxy).
- Publish without prior `pipeline_passed` → 409.
- Admin suspends → catalog no longer shows; existing licensees still download (verified in Slice 11 tests).

---

### Slice 10 — Catalog read + search + filters + related frameworks
**Add:**
- `app/modules/explore/router.py` + `service.py`:
  - `GET /v1/explore/frameworks?q=&page=&page_size=20&sort=newest|top-rated|most-purchased|price_asc|price_desc&sector=&industry=&function=&category=&license_type=&complexity=&org_size=&lifecycle_stage=&jurisdiction=&price_min=&price_max=&attested=true|false` (FR-EXP-001..004).
  - `GET /v1/explore/frameworks/{id}` (FR-EXP-006): full payload + artifact list (artifact bodies NOT in response; only metadata + downloadable URL gated by Slice 11 download endpoint). Includes **`preview_url: string | null`** (FR-EXP-007) — presigned GET (15min TTL) for the designated preview artifact, or null if none designated. Public, no auth/license/KYC required (per Cross-cutting concern 7). Rate-limited 60/min per IP via Redis fixed-window.
  - `GET /v1/explore/frameworks/{id}/related` (FR-EXP-009): up to 6 frameworks ordered by `(tag_overlap_jaccard, category_match, sector_match, sub-jaccard on title tsvector)`.
- BR-EXP enforcement:
  - BR-EXP-001: WHERE `status='published'` only.
  - BR-EXP-002: WHERE `contributor_id != current_user_id` (when authenticated).
  - BR-EXP-003: GIN tsvector + composite indexes; integration test asserts `EXPLAIN ANALYZE` < 2s on a 10k-row fixture.
- Sort shims: `top-rated` orders by `0` (no reviews until Phase 3), `most-purchased` orders by `0`; integration tests confirm endpoints accept the sort param + return data ordered by created_at fallback w/ a `X-Sort-Shim: true` response header for transparency.
- Public-read: endpoints work unauthenticated (FR-EXP-008). `current_user_id` derived from token if present, used for BR-EXP-002 + Owned-badge (FR-EXP-011 — license check delegated to Slice 11).

**OpenAPI updated.**

**Edge cases tested:**
- Search by partial title + tag → returns expected.
- Filters combined (sector AND price_range AND complexity) → returns correct subset.
- Unauthenticated request → 200, framework body returned w/o download URLs (FR-EXP-008).
- **Incomplete authenticated user (blank `display_name` OR KYC unverified OR KYC pending OR no role) browse + search + detail → 200** (all read endpoints work; no `error_code` returned on read paths). Email-unverified people exercise the same read path as unauthenticated visitors because Phase 1 login blocks them.
- **Incomplete user `preview_url` access → 200** (public per Cross-cutting concern 7).
- Authenticated Contributor's own framework → excluded from catalog (BR-EXP-002).
- Suspended / unpublished framework → not in catalog (BR-EXP-001).
- Related-frameworks excludes self + Contributor's own.
- Pagination cursor stable on insert.
- Detail payload includes `preview_url` only when `preview_artifact_id` is set; otherwise `null`.
- Preview URL rate-limit: 61st request in 1 min from same IP → 429.
- `EXPLAIN ANALYZE` integration test against 10k-row fixture asserts catalog query < 1s, filter combos < 2s.

---

### Slice 11 — License model + Operator library + download gate
**Add:**
- Service: `grant_license(framework_id, operator_id, type, transaction_id=None, expires_at=None)` (admin-only in Phase 2; called by Phase 3 purchase flow later w/ real `transaction_id`). UNIQUE on `(framework_id, operator_id)` enforces BR-FWK-004 single license per Operator per Framework. Sets `version_at_grant` to current `frameworks.version`. Audit row.
- Service: `list_operator_library(operator_id, page, page_size)` (FR-FWK-011).
- Service: `request_artifact_download(framework_id, artifact_id, user, ip)` (FR-FWK-012):
  - License check: active license for `operator_id, framework_id`.
  - **Operator KYC check** via Phase 1 `require_kyc_verified()` (approved deviation — BR-AUTH-002 expansion).
  - Artifact must belong to a `framework_version` the license covers (current or any prior version the licensee held — FK chain via `framework_version_artifacts`).
  - On pass: issue S3 presigned GET (15m TTL). Insert `artifact_downloads` row (BR-FWK-006).
- Router: `GET /v1/library` (Operator scope), `GET /v1/frameworks/{id}/artifacts/{aid}/download` (Operator scope w/ license + KYC deps), `POST /v1/admin/licenses` (admin scope; takes `{framework_id, operator_id, type, expires_at}`). Enterprise license uses this admin endpoint exclusively (admin-mediated invoice flow).
- Team license seat-tracking: `licenses` gets `seats_used INTEGER DEFAULT 1` + `seats_total INTEGER`. For `team` type, default `seats_total=10`. Phase 3 attaches seat allocation flow; Phase 2 only persists the field.

**OpenAPI updated.**

**Edge cases tested:**
- Operator w/o license downloads → 403.
- Operator w/ license but KYC unverified → 403 + `error_code="kyc_required"` + `onboarding_url="/settings/onboarding"`.
- **Operator w/ license but KYC pending → 403 + `error_code="kyc_required"`** (pending ≠ verified).
- Operator w/ license + KYC verified → 200, presigned URL returned, `artifact_downloads` row written.
- Operator licensed on v1.0.0 attempts download from v2.0.0 artifact → 403 (license covers v1.0.0 only).
- Suspended framework download by existing licensee → 200 (existing licensees retain access).
- Admin grants duplicate license → 409.
- Enterprise license w/o admin → 403.
- 100 concurrent downloads → each gets unique audit row; presigned URLs are not the same string.

---

### Slice 12 — Frontend (Contributor dashboard + Explore + Detail + Library)
**Add (mobile-first per Brand Book §11–13):**
- Public:
  - `frontend/src/app/(public)/explore/page.tsx` (SSR) — catalog grid + filter sidebar + search.
  - `frontend/src/app/(public)/explore/[id]/page.tsx` (SSR) — framework detail.
  - `frontend/src/components/modules/explore/*`: `FrameworkCard`, `FilterSidebar`, `SearchInput`, `RelatedFrameworks`, `PreviewArtifactBlock`.
- Auth-gated:
  - `frontend/src/app/(auth)/dashboard/frameworks/page.tsx` — Contributor list.
  - `frontend/src/app/(auth)/dashboard/frameworks/new/page.tsx` — Create framework wizard.
  - `frontend/src/app/(auth)/dashboard/frameworks/[id]/page.tsx` — Edit framework, artifact upload, pipeline status panel, version radios, Publish button.
  - `frontend/src/app/(auth)/dashboard/frameworks/[id]/analytics/page.tsx` — FR-FWK-010 (views; purchases + revenue + avg-review shimmed `0` until Phase 3).
  - `frontend/src/app/(auth)/library/page.tsx` — Operator library + download links.
- `frontend/src/components/modules/frameworks/*`: `FrameworkForm`, `ArtifactUploader` (drag-drop + progress + scan/processing/PII/rarity badges), `PipelineStatusPanel` (per-check green/red w/ explanation tooltip), `PublishButton` (enabled only when all green or soft-fail acknowledged), `VersionRadios` w/ prior-version display, `SoftFailAcknowledgement` modal, `RedactionAcceptance` modal.
- Token store + middleware from Phase 1 Slice 9 + 10 already in place; routing redirects respected.
- **Incomplete-user handling.** API client wrapper intercepts 403 responses carrying `error_code` ∈ {`kyc_required`, `profile_required`, `role_required`} → routes browser to `/settings/onboarding` (Phase 1) preserving original intent via `?next=<encoded URL>` query param. Read endpoints continue to work — only action attempts trigger the redirect. Catalog + detail + preview render identically for incomplete users; the only UI difference: action buttons (Publish, Upload, Download, Create Framework) become an "Complete onboarding to continue" CTA that links to `/settings/onboarding`. Email-unverified visitors stay in the login/verify-email path before any authenticated marketplace action is attempted.

**Test:**
- vitest component: filter combos, search debounce, pipeline status renderer per state matrix, 403-w/-error_code interceptor routes to `/settings/onboarding?next=...`.
- playwright e2e `framework-publish.spec.ts`: Contributor → KYC-verified → create draft → upload PDF → pipeline runs → all green → Publish → catalog shows it → log out → unauth user views it → log in as Operator (test-license-seeded) → download → audit row exists.
- **playwright e2e `incomplete-user.spec.ts`** (new): register Contributor → email-verify → log in → can browse `/explore` + view detail + see preview → click "Create Framework" → routed to `/settings/onboarding?next=/dashboard/frameworks/new` → submit KYC docs → status `pending` → still routed to onboarding for create attempt → admin verifies → KYC `verified` → create succeeds. Same flow as Operator → KYC pending → download attempt → onboarding redirect.
- playwright e2e `explore.spec.ts`: unauth browse → search → filter → click detail → preview visible → click download → login prompt.

---

## Per-slice working agreement

After each slice the agent:
1. Opens with one-line summary + FR/BR mapping.
2. Lists files to be created/modified before writing.
3. Writes failing test first per `tdd` skill.
4. Implements minimum to pass.
5. Runs `uv run ruff check && uv run mypy app && uv run pytest --cov` (backend) or `pnpm test` (frontend).
6. **Stops.** Waits for human review + commit. No autonomous next slice.

---

## Risk flags

- **Worker memory footprint:** Presidio + spaCy `en_core_web_lg` + datasketch + scikit-learn + Poppler in one Celery worker dyno = ~2.5GB RAM. Render starter dyno = 512MB. Pre-Slice-3 deploy task: provision Render Standard (2GB) or Pro (4GB) worker. Alternatively split into two worker pools (`pipeline-heavy` vs `notifications`) — defer until needed.
- **Brave Search API cost drift:** ~$0.012/artifact amortized at gating + caching assumptions. If gating rate or cache hit rate diverges from assumption, cost rises. Add monthly spend alarm + degrade-to-NULL fallback. Stage B is the only paid line item in the pipeline.
- **ClamAV signature DB freshness:** `freshclam` must run in worker on a schedule. Container restart loses cache. Mount a small volume or rely on daily refresh; both worker startup latency.
- **MinHash LSH index drift on unpublish/suspend:** removed artifacts must be evicted from LSH so they don't pollute future internal-rarity scores. Tested in Slice 9 + 11.
- **tsvector update cost** at scale: if catalog reaches Phase 5 scale, full tsvector recompute on every metadata edit slows down. Mitigated by trigger-driven incremental update; pre-launch fine.
- **Top-tf-idf phrase quality** for external rarity: too-common phrases (e.g. "five forces analysis") return millions of hits and over-penalize legitimate framing. Mitigated by stop-phrase blocklist + minimum-length 5-word window. Track soft-fail acknowledgement rate as the signal-quality metric.
- **Version-aware downloads:** licensees of an old version must keep that version's artifacts downloadable forever. `framework_version_artifacts` join is the truth source. If we ever delete old artifact S3 objects to save cost, must add a separate "archive-after-N-licensees-stop-paying" rule; defer.
- **Enterprise license admin-mediated flow:** opens an admin surface that bypasses purchase pipeline entirely. Audit every grant. Phase 3 should reconsider whether to fold enterprise into purchase flow w/ a higher tier or keep as admin manual.
- **Reviews schema in Slice 1 but no flow:** test fixtures should not insert review rows until Phase 3 — keep table empty in dev/staging to avoid Phase 2 UI accidentally rendering stale fixtures.

---

## Verification (end-to-end after Slice 12)

1. `docker compose up` (api, db, redis, beat, worker, frontend, clamav).
2. Backend: `uv run pytest --cov=app/modules/frameworks --cov=app/modules/explore --cov=app/workers/tasks/processing` → ≥ 80% line coverage.
3. Frontend: `pnpm test` + `pnpm exec playwright test tests/e2e/framework-publish.spec.ts tests/e2e/explore.spec.ts`.
4. Manual smoke (full happy path):
   - Login Contributor (verified KYC from Phase 1) → create framework w/ metadata + price + license types → upload one PDF → wait 30s → see pipeline status panel turn green (virus clean, no PII, internal_rarity=1.0 since first upload, external_rarity from Brave) → click Publish → catalog shows framework.
   - Logout → browse `/explore` unauth → find framework → click into detail → see preview block + artifact list → click download → login redirect.
   - Login Operator (verified KYC) → admin grants license → `/library` shows framework → click download → presigned URL fires → file lands → `artifact_downloads` row exists.
   - Login Contributor → create new version → pick "Improvement" radio → enter change_log → unpublish-republish cycle → tsvector updated → version_at_grant remains `1.0.0` for prior licensee.
   - Admin → suspend framework → catalog hides → existing licensee still downloads.

---

## Out of scope (later phases)

- **Reviews flow** (FR-FWK-014) — schema only Slice 1; full flow Phase 3 after first license can exist.
- **Watchlist** (FR-EXP-010) — Phase 5 Collections.
- **Purchase + payment flow** — Phase 3 (FR-FIN-*).
- **Stripe / Paystack webhooks** — Phase 3.
- **Embedding-based related frameworks** — Phase 5 only if tag/category baseline underperforms.
- **Attestation workflows** — Phase 4 (FR-ATT-*).
- **Project workspaces, proposals, milestones** — Phase 4 (FR-PROJ-*).
- **Developer Platform (API keys, partner webhooks, partner endpoints)** — Phase 5 (FR-DEV-*).
- **Saved searches + email alerts** — Phase 5.
- **Meilisearch / Typesense migration** — Phase 5 only if catalog > ~50k frameworks.
- **Subscription / perpetual license types** — Phase 5 or later.
