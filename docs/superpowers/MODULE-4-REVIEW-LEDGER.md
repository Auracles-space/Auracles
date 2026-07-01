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

## Carry-forward watch items (later slices)

- §4.8 grace-then-revoke: Slice 3 widens `revoke_overdue_attestations` from {accepted} to {accepted, in_review} AND adds +24h grace before revoke — a Module 3 behavior change (instant → +grace). Verify existing revoke tests updated, not masked.
- `submit_report` precondition moves accepted → in_review (Slice 4). Existing report tests must be re-pointed.
