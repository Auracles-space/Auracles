# Attestation Module 4 — Review Workspace · Review Ledger

Plan: docs/superpowers/plans/2026-07-01-attestation-module-4-review-workspace.md
Spec: docs/superpowers/specs/2026-07-01-attestation-module-4-review-workspace-design.md
Branch: main
Reviewer: this session (backend reviewer)

## Slice 1 (Tasks 1–3) — commits 523cf5e..df4678e — verdict: PASS. 0 Critical, 0 Important.

- Range: 3 commits (523cf5e T1 rubrics, 8eff9a7 T2 models/enums, df4678e T3 migration+seed); 6 files, +843.
- Gates: 10 slice tests pass; broad attestation unit suite 37 pass; whole-repo `ruff check .` clean; `mypy app` clean (211 files); alembic down→up round-trip clean (0048↔0047); single head 2026_07_01_0048.
- Rubric weights verified: quality 8 dims=1.000, compliance 6=1.000, expert 6=1.000, provenance 5=1.000; 25 total dims, 4 methodology rows — matches spec §3.4 verbatim.
- `weighted_overall` quantizes to 0.01 → [1.00,5.00] fits numeric(3,2) (spec §3.5). All-5s → 5.00; missing dim raises; out-of-range raises.
- Schema matches models: `in_review` enum ADD VALUE AFTER 'accepted' (autocommit_block, IF NOT EXISTS — precedent 0041); 4 new Attestation cols + `late_submission_count`; 5 tables; scores CHECK `score IS NULL OR 1..5`; unique(attestation_id,dimension_id) ready for T6 upsert.
- Downgrade drops tables + annotation/clarification enums (checkfirst); leaves `in_review` value in place — documented, standard PG limitation, re-upgrade guarded by IF NOT EXISTS.
- Seed idempotent: bulk_insert runs once per migration application; round-trip re-seeds 25 fresh (drop→recreate), no doubling.

### Minor findings (Slice 1)

- T3/Minor: `attestation_annotations.artifact_id` FK to artifacts.id has no `ondelete` → RESTRICT, inconsistent with sibling `attestation_id` CASCADE. Deleting an artifact is blocked while an annotation references it. Likely fine (provenance preservation) but call it out — if artifacts are hard-deleted anywhere, this blocks it. Decide at final review: SET NULL vs keep RESTRICT.
- T2/Note: `AttestationRubricScore(UpdatedAtMixin, CreatedAtMixin, Base)` carries both mixins; migration defines created_at/updated_at with server_default now(), no DB-level onupdate (ORM handles updated_at). Consistent, no action.

## Slice 2 (Tasks 5–9) — commits 1baae73..77d96c4 (+ eb323ac gate fix) — verdict: PASS. 0 Critical, 0 Important.

- Range: 4 code commits (1baae73 T5 start-review, ca05ead T6 rubric upsert, 87460a2 T7 annotation CRUD, 77d96c4 T8 schemas+router+OpenAPI); T9 = slice gate (no commit). 5 files, +1517/-3. Branch `attestation/module-4`.
- Gates: 16 slice tests pass (8 service unit-style + 8 endpoint integration); whole-repo `ruff check .` clean; `mypy app` clean (212 files); workspace tests green.
- Gate fix: committed `77d96c4` alone fails ruff I001 (import block in test_attestation_workspace.py). Implementer left the isort fix uncommitted. Folded into `eb323ac` (test-file import reorder, no behavior change) so Slice 2 is gate-clean.
- `start_review`: `accepted → in_review`, idempotent (returns early when already in_review); gates on content_ack (`content_ack_at` + `content_ack_version`) and a valid current CoI (signed, not expired); sets `review_started_at`; audits `attestation_review_started` with review_type only. 404-hides on assignee mismatch, 409 on wrong state.
- `upsert_rubric_score`: FOR UPDATE lock on attestation row serializes concurrent upserts on the same (attestation, dimension) → no unique-constraint race; dimension resolved by review_type+version+key, unknown key → 422; score double-guarded (schema `ge=1,le=5` + service 1..5).
- Annotation CRUD: `create/update/delete` gated to `in_review`; `list` allows `{in_review, report_submitted}`, read-only (lock=False); annotation_type double-guarded (schema Literal + service `ANNOTATION_TYPES`); `_load_owned_annotation` re-checks workspace visibility before touching a child row (no IDOR).
- `db.in_transaction() → rollback` pattern is the module-wide convention (matching/dispute/report/service/application/credential all use it) — consistent, not new.

### Minor findings (Slice 2)

- T6/Minor: `RubricScoreResponse` echoes `dimension_id` (UUID) not the `dimension_key` the client PUT in the URL. Frontend must map UUID→key. Harmless; consider echoing key at report-render time (Slice 4).
- T5–T7/Minor (test completeness): uncovered branches — `start_review` 422 paths (missing content_ack, absent/expired CoI); the 409 wrong-state gate on scoring/annotation against a non-`in_review` attestation; RBAC 403 for a non-attestor role on workspace endpoints (only 401/404 covered); update/list against `report_submitted`. Slice 3/4 submit-gate work likely exercises some state gates — confirm then, else backfill.
- T7/Note: `AnnotationUpdateRequest(AnnotationCreateRequest)` lets update replace `artifact_id`. Intended (full-field replace). No action.

## Slice 3 (clarifications + SLA pause + grace revoke) — commits 4d5d6aa..4fc0c14 — verdict: PASS after fixes. 1 Critical + 1 Important, both fixed in review.

- Range: 5 commits (4d5d6aa send+SLA extend, f78f7d2 respond+SLA remainder trim, 7991a08 expiry sweep + grace-aware revoke, 847ab09 endpoints, 4fc0c14 format). 12 files, +1435/-7.
- Gates after review fixes: 40 slice+regression tests pass; full `-k "attestation or notification"` sweep 177 pass (see migration-isolation note); whole-repo `ruff check .` clean; `mypy app` clean (213 files).
- SLA accounting verified: send extends `completion_due_at` by full `response_hours` up front and sets clarification `response_due_at`; respond returns the unused remainder (`completion_due_at -= (response_due_at - now)` when positive) → net SLA cost = time actually consumed; expiry keeps the full extension (whole window legitimately spent waiting). None-safe on `completion_due_at`.
- Concurrency verified: send locks attestation FOR UPDATE (serializes the open/limit count checks); respond locks attestation then clarification FOR UPDATE; expiry is per-row FOR UPDATE with `status=='open'` recheck → idempotent.
- Grace revoke (§4.8) verified: reads `attestation_completion_grace_hours` (default 24, min 0); cutoff = now − grace; status filter widened `{accepted}→{accepted, in_review}`; cutoff applied in both candidate select and locked recheck. New tests cover past-grace revoke and in-grace no-op.

### CRITICAL (fixed in review — 4117fb9)

- Grace widening broke pre-existing Module 3 test `test_revoke_overdue_attestation_reoffers_and_clears_payee` (test_attestation_matching.py): it set `completion_due_at = now-1h`, now inside the 24h grace → revoke no longer fires → `assert 0 == 1`. The implementer's slice gate ran only the new slice files and missed the broader-suite regression — exactly the carried-forward watch item. Fixed: pushed the fixture to `now-25h` (past grace), preserving original intent. This is a reviewer-caught gate failure; the committed slice was NOT green across the module.

### IMPORTANT (fixed in review — 5ebae5f)

- Clarification notification dedupe was too coarse. Dedupe key is `(user_id, dedupe_key, channel)` unique-enforced; the notify helpers used a static suffix (`clarification-requested` / `clarification-answered`). With two clarifications allowed per attestation, the second event collapsed to the same key and its notification was silently dropped; expiry reused the `answered` suffix and collided further. Fixed: threaded `clarification_id` into the dedupe suffix (helpers + 3 call sites). No test asserted the old behavior.

### Minor findings (Slice 3)

- Slice3/Minor: `ClarificationCreateRequest.question` and `ClarificationRespondRequest.response` skip the module's `_ensure_safe_prose` hardening (`<>`/control-char reject) applied to other attestation prose fields. Stored and shown in-thread to the other party. Defense-in-depth inconsistency — add the validator for parity. (Notification bodies are static, so not reflected there.)
- Slice3/Minor: on expiry, the attestor is notified via `notify_clarification_answered` ("The requestor answered your clarification question") — factually wrong for an unanswered/expired clarification. Copy-only; consider a distinct "clarification expired" notification in Slice 4/polish.

## Slice 4 (submit gate + 8-section report PDF + late/grace finalization) — commits 7f26c89..b8717b8 — verdict: PASS after fix. 0 Critical, 1 Important (fixed in review).

- Range: 4 commits (14fc86e quality gate, 3201b9c gated submit + conditions + late-flag, 5cf6089 eight-section report PDF, b8717b8 workspace submission regression fixes). 8 files, +1348/-44.
- Gates after review fix: 25 slice tests pass; broad attestation suite 106 pass (integration access/clarifications/consent/offers/requests/workspace + unit rubrics/scoring/workspace/clarifications/ranking/beat/coi/upload); whole-repo `ruff check .` clean; `mypy app` clean (214 files). Migration-cycle files excluded per the batch-isolation note below.
- Watch item RESOLVED: `submit_report` precondition moved `accepted → in_review`. Implementer correctly re-pointed the two existing report tests in test_attestation_matching.py — `test_assigned_attestor_uploads_evidence_and_submits_report` (fixture → `in_review`, `review_type="quality"`, seeds full rubric scores + long summary) and `test_unassigned_attestor_cannot_submit_report` (403→404). Broad suite ran green; the Slice-3-Critical failure mode did not recur.
- Quality gate (§4.7) verified: returns ALL failures at once; enforces every dimension scored+commented, conditions-required-iff-conditional, non-approved-requires-annotation, min-words (config `attestation_report_min_words`, default 150), contact-info block (config `attestation_report_block_contact_info`, default on), no open clarification. Config readers default safely on non-int. Unit tests assert real per-rule failure content + aggregation (≥3).
- Submit path verified: gate runs inside the txn before any state write, 422 with itemized `detail` list on failure; sets `conditions`, `rubric_version`; late path stamps `submitted_late`, increments `AttestorProfile.late_submission_count` under `with_for_update()`, audits `attestation_late_submission`; `_load_assigned_attestation_for_update` now 404-hides on assignee mismatch (was 403) — consistent with module existence-hiding. `report_key` is deterministic (`attestation-reports/{id}/report.pdf`) and matches the PDF task key → no orphaned S3 object.
- PDF (8 sections) verified: split into `_build_report_context` / `_build_report_html`; dimension table, weighted overall, findings from annotations, conditions, attestor identity + credentials + verification level, supplementary notes. Column attrs are read after session close but none are lazy relationships (no DetachedInstanceError); pdf unit test confirms.

### IMPORTANT (fixed in review — pending commit)

- OpenAPI contract drift. `conditions: str | None` was added to the `AttestationReportSubmitRequest` Pydantic model but NOT to `contracts/openapi.yaml`. The frontend client is generated from that contract (CLAUDE.md rule 7 "OpenAPI first"), so a conditional/rejected outcome — which the gate REQUIRES conditions/annotations for — could not be submitted from the generated client. Fixed by adding the field to the contract, matching FastAPI's actual generated shape (`anyOf: [{type: string, maxLength: 10000}, {type: 'null'}]`, not required). Verified against `app.openapi()` output; YAML re-parsed clean.

### Minor findings (Slice 4)

- Slice4/Minor: contact-info phone pattern `(?:\+?\d[\d\s().-]{7,}\d)` false-positives on legitimate numeric spans — e.g. a report citing "fiscal years 2020-2021" or a long figure matches and is blocked with the misleading "Report contains contact information" message. Config-disableable and the block itself is spec-mandated (§4.7), so NOT auto-changed — human decides whether to tighten the phone heuristic or reword the failure message. Untested/latent (passing tests use `a@b.com` + digit-free `_long_text`).
- Slice4/Minor: PDF `weighted_overall(score_map, attestation.review_type or "")` raises `ValueError` when `review_type` is empty or a dimension is unscored. Any pre-Module-4 `released`/`closed` attestation regenerating its PDF (no review_type, no rubric scores) would crash the task. Greenfield/pre-launch so latent — guard with a default/skip when the rubric context is absent.
- Slice4/Minor: `min_words` counts summary + rubric comments + conditions but excludes `scope`, while the contact check includes `scope`. Confirm the asymmetry is intended.
- Slice4/Minor: `supplementary_notes` renders `str(attestation.evidence_references)` — a raw Python dict repr in the PDF. Cosmetic; render structured or a labeled key list.

### Un-folded earlier-slice items (still open at module close)

The three "Slice 4 open items to fold in" from earlier slices were NOT addressed in Slice 4 (diff did not touch clarification_service/notifications/workspace schemas). Still open — human decides whether they block merge:
- `_ensure_safe_prose` on clarification question/response (Slice 3 Minor).
- distinct "clarification expired" notification instead of reusing "answered" copy (Slice 3 Minor).
- `RubricScoreResponse` echo `dimension_key` not just `dimension_id` (Slice 2 Minor).

## Carry-forward watch items (later slices)

- ~~§4.8 grace-then-revoke widening~~ — RESOLVED in Slice 3. Widened + grace confirmed; the masked Module 3 revoke test was caught and fixed (4117fb9).
- ~~`submit_report` precondition moves accepted → in_review (Slice 4)~~ — RESOLVED in Slice 4. Both existing report tests re-pointed; broad report/matching suite ran green. The lesson held: running the broader suite (not just new slice files) confirmed no silent status-precondition regression.
- ~~Slice 4 open items to fold in~~ — NOT folded in during Slice 4; carried to module-close decision (see Slice 4 "Un-folded earlier-slice items"). All Module 4 slices reviewed; no further slices.

## Note: migration-test batch isolation

Running `pytest -k "attestation or notification"` reports 2 failures in `test_attestation_review_type_migration.py`; both PASS in isolation. Migration tests downgrade/upgrade the shared DB and interfere when batched with other DB tests. Pre-existing harness quirk, unrelated to Slice 3. When gating, run migration-cycle tests separately.
