# Post-Publication Plagiarism Hardening (Option C) — future doc

## Status

**Not scheduled. Data-gated.** Build this only once real submission volume shows
actual plagiarism the recalibrated band gate misses. Pre-building before that is
guessing at thresholds with no abuse data. This doc captures the design so the
decision trail is not lost.

## Context

The Phase-2 rarity gate was reframed (see
`2026-06-10-post-phase-4-marketplace-polish-backlog.md` Slice 2): internal
MinHash-Jaccard now blocks only **near-duplicates** (≥~0.90) and emits a
non-blocking notice for the 0.70–0.90 similarity band. That fixed the
anti-competitive "same problem = blocked" bug.

Two gaps remain, both acceptable at launch but worth closing later:

1. **Paraphrase plagiarism slips through.** Jaccard measures literal shingle
   overlap. A reworded copy (synonyms, reordered sentences, same substance) has
   low Jaccard and passes every band. The gate cannot see it.
2. **Pre-publish only.** The gate runs during the artifact pipeline. A copy
   published *before* its source, or a copy of content added after the copy was
   already live, is never re-checked.

## Option C — containment + verbatim-run detection

Replace/augment raw symmetric Jaccard with a **copy-oriented** signal at the hard
band (the notice band can stay Jaccard-based):

- **Asymmetric containment** — "how much of Framework X appears inside Framework
  Y" (and vice-versa). Containment catches a short copied core embedded in a
  larger original doc, which symmetric Jaccard dilutes away.
- **Longest verbatim runs** — length/coverage of the longest exact shared token
  sequences. Long verbatim passages are a strong copy signal; shared scattered
  vocabulary is not.
- **Optional semantic layer for paraphrase** — cosine similarity over the
  existing `metadata_vector` / embedding already produced in processing. High
  semantic similarity + low literal overlap = paraphrase candidate. Tune
  carefully: same-topic originals are also semantically close, so this feeds
  *review*, not an auto-block.

Output: a `copy_confidence` score + evidence (which passages, containment %,
matched Framework). High confidence → hard block (pre-publish) or flag
(post-publish). Calibrate all thresholds on labelled data, same discipline as the
band calibration.

## Post-publication enforcement

- **Scheduled re-scan** (Celery Beat): periodically re-run the copy detector on
  published Frameworks against the current published corpus, so copies that
  evaded the pre-publish check (or predate their source) surface.
- **Flag → admin review → pull.** High `copy_confidence` raises a moderation flag,
  not an automatic takedown. Admin reviews evidence and, if confirmed, **pulls the
  publication via the existing `suspend_framework`**
  (`admin/service.py:145`, `POST /v1/admin/frameworks/{id}/suspend`,
  audit `framework_suspended`) — no new takedown plumbing. Add a structured
  `suspend_reason` (e.g. `plagiarism`) for analytics.
- **Notify both parties.** Reuse the notifications module: alert the original
  author (their content was copied) and the suspended contributor (with the
  evidence + an appeal path). Suspension is reversible if the appeal succeeds.
- **Audit everything**: `plagiarism_flagged`, `framework_suspended`
  (reason=plagiarism), `plagiarism_appeal_*`.

## Reuse (no new infra where avoidable)

- MinHash/SimHash + `metadata_vector` already produced in
  `workers/tasks/processing/*`.
- Admin suspend + audit + notifications all exist.
- Beat scaffolding exists.
- Net-new: the containment/verbatim scorer (new processing stage), the
  `copy_confidence` field + evidence storage, the re-scan Beat task, the
  moderation-flag → admin queue surface, and an appeal flow.

## Out of scope

- Cross-language copy detection.
- Image/diagram plagiarism.
- DMCA legal workflow / counter-notice (handle operationally, not in-app, until
  volume justifies).
- Auto-takedown without admin review — always human-in-the-loop for suspensions.

## Trigger to revisit

Pull this forward when any of: (a) confirmed paraphrase-plagiarism reports
accumulate, (b) the notice band shows recurring true copies that Jaccard under-
scored, or (c) contributor complaints about copied content reach a threshold worth
the engineering cost.
