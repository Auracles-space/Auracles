# Attestation Module 3 — AMM Matching · Review Ledger

Plan: docs/superpowers/plans/2026-06-30-attestation-module-3-amm-matching.md
Spec: docs/superpowers/specs/2026-06-30-attestation-module-3-amm-matching-design.md
Branch: main
Reviewer: this session (backend reviewer)

## Tasks

- [x] Tasks 1–3: complete (commit b8e9fcc, review clean — 0 Critical, 0 Important)
  - Gates: 17 tests pass; whole-repo `ruff check .` clean; `mypy app` clean (210 files); alembic head = 2026_06_30_0047 (single head, sequence correct).
  - Task 1 (schema): `AttestationOffer.match_score` Numeric(4,3) + `score_breakdown` JSONB; `AttestorProfile.coi_reminder_sent_at`; migration 0047 (down_revision 0046, downgrade present + tested up/down).
  - Task 2 (scoring): weights verbatim (0.30/0.25/0.20/0.15/0.10, sum 1.0); swap constants 0.5; per-factor fns + `compute_match_score`; `cap<1` → ValueError.
  - Task 3 (CoiEntry): optional `subject_id`/`subject_kind`; legacy entries still validate.

- [x] Task 4: complete (commit 8d64630, review clean — 0 Critical, 0 Important)
  - Gates: 19 tests pass (ranking unit + offers integration + matching regression); whole-repo `ruff check .` clean; `mypy app` clean (210 files).
  - FIFO selector replaced with `_rank_eligible_attestors` + `ScoredCandidate`; CoI eligibility folded into SQL (`coi_signed_at IS NOT NULL AND coi_expires_at > now`); conflict screen on `subject_id` (malformed → WARNING+skip, never excludes); availability cap via `attestation_concurrency_cap` config; tie-break score DESC → approved_at ASC → user_id (matches spec verbatim; `approved_at` is NOT NULL so Python sort safe).
  - Scores wired onto offers (`match_score`/`score_breakdown`) + audit metadata `scores` dict (ids+floats only, no PII).
  - Fixture change to `test_attestation_matching.py` legit & necessary: new CoI gate requires signed CoI on profiles, else zero candidates — does not mask regression.

- [x] Task 5: complete (commit c5674f5, review clean — 0 Critical, 0 Important)
  - Gates: 13 tests pass; whole-repo `ruff check .` clean; `mypy app` clean (210 files).
  - `send_coi_resign_reminders` (daily Beat, crontab 02:00); `notify_coi_expiring`/`notify_coi_lapsed` via `dispatch_project_notification.delay` (user-targeted, dedupe_key, no PII/secrets); `coi_reminder_sent_at` dedup.
  - One-reminder-per-signing-cycle (expiring OR lapsed, not both) is plan-mandated (plan line 1126/1343) + spec §6 — impl matches plan code verbatim. NOT spec drift; do not "fix" to fire both.
  - Beat wrapper mirrors existing 5 tasks (bind=True, run_async, task_started/completed logs). Schedule entry added.

## Follow-up fix (commit 726972b) — addresses 3 of the 5 Minors

- Task5/Minor (broker-down): FIXED. `notify_coi_expiring`/`notify_coi_lapsed` now return `bool` (True=enqueued, False=dispatch failed). `send_coi_resign_reminders` only stamps `coi_reminder_sent_at` + counts on a confirmed enqueue → transient broker outage no longer silently skips an attestor for a year. Test `test_failed_dispatch_does_not_mark_reminded`.
- Task5/Minor (schedule assertion): FIXED. Registration test now asserts `crontab(hour=2, minute=0)`.
- Task4/Minor (all-screened test gap): FIXED. `test_all_screened_out_marks_needs_admin` covers `offer_next_cohort` → needs_admin via the availability cap.
- DEFERRED (accepted, not worth the churn): migration test location (`unit/` vs `integration/`) — cosmetic; Task4 N+1 active-count — MVP scale, SQL-capped pool.
- Re-review gates: broad attestation+workers suite 68 passed; whole-repo ruff clean; mypy clean (210); alembic 0047↔0046 round-trip clean.

## Final whole-branch review (241276c..726972b, opus) — verdict: MERGE. No Critical, no Important.

- Range: 3 code commits (b8e9fcc, 8d64630, c5674f5); 17 files, +1445/-15.
- Gates: full attestation+workers suite 66 passed; whole-repo `ruff check .` clean; `mypy app` clean (210); alembic up→down→up round-trip clean (0047↔0046).
- FIFO selector cleanly retired: `_matching_attestor_ids` fully removed, single caller now `_rank_eligible_attestors`, no dangling refs.
- Security pass: no new endpoint/attack surface (internal service); CoiEntry.subject_id Pydantic-validated UUID; audit `scores` + `score_breakdown` carry ids+numbers only (no PII/secrets); notify logs user_id only on error, generic body; Escrow untouched; migration nullable+reversible.
- Score range safe: max weighted sum 1.0 → fits Numeric(4,3). breakdown stores raw factors, score rounded (intentional, harmless).
- Design note (not a defect): malformed CoI subject_id → skip+WARNING, never excludes (spec §4 decision; tension with deny-by-default is documented & accepted).
- All 5 Minors below are non-blocking; recommend a small follow-up for Task5 broker-down reliability + the two test-coverage gaps. None gate merge.

## Minor findings (for final whole-branch review)

- Tasks1-3/Minor: migration test landed at `tests/unit/test_attestation_amm_matching_migration.py` but it does a real DB alembic up/down — plan specified `tests/integration/` and repo convention puts DB-touching migration tests there (cf. `tests/integration/test_attestation_access.py`). Functional, passes; pure location/category. Consider moving in final review.
- Tasks1-3/Note: `compute_match_score` returns `dict(factors)` as breakdown — stores ALL passed keys verbatim, not only WEIGHTS keys. Caller-controlled (Task 4 builds the factors dict, exactly the 5 WEIGHTS keys — verified), so no leak risk.
- Task4/Minor: `_active_assignment_count` runs one COUNT query per surviving profile → N+1 over the eligible pool. MVP-acceptable (pool is small, capped by SQL hard-filter); consider a single grouped COUNT if pools grow. Mirrors the Module 1 directory N+1 note.
- Task4/Minor: offer-level "all candidates screened out → needs_admin" path (every eligible profile conflicted/at-cap/expired) is covered at the ranking-unit level (each exclusion gate tested) but not re-asserted through `offer_next_cohort`. Existing needs_admin offer test covers the empty-SQL-pool case. Consider one offer-level all-screened test at final review.
- Task5/Minor: a failed `dispatch_project_notification.delay` (broker down) is swallowed in the notify wrapper, yet `coi_reminder_sent_at` is still set and `sent` incremented — so a transient broker outage marks the whole sweep "reminded" and skips those attestors until next signing cycle. MVP-acceptable (best-effort notifications, mirrors existing notify_* pattern). Consider only setting the timestamp on confirmed enqueue if reminder reliability matters.
- Task5/Minor: `test_coi_resign_reminder_task_is_registered_in_beat_schedule` asserts the task name but not the schedule value (`crontab(hour=2, minute=0)`), unlike the owner-consent registration test which asserts `3600.0`. Add the schedule assertion at final review.
