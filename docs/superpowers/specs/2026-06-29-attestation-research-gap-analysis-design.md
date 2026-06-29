# Attestation Build Guide — Master Gap Analysis & Decomposition

- **Date:** 2026-06-29
- **Status:** Draft (awaiting review)
- **Author:** William Ikeji (architect) + agent
- **Module:** `attestation` (+ `financials`, `explore`, `settings` touchpoints)
- **Related FRs:** FR-ATT-*, BR-ATT-*, FR-FIN-*
- **Source of truth:** `docs/Auracles Attestation — Product Development Workflow.md`
  (v1.0, 29 Jun 2026 — the authoritative 6-module developer build guide)

## Purpose

This is the **umbrella gap analysis** for the full Attestation build guide. It compares each of
the guide's six modules against the already-implemented `app/modules/attestation/` code, marks
every capability **Built / Partial / Missing**, and lays out a **decomposition roadmap** — one
spec → plan → implementation cycle per module, in the guide's own build-priority order.

This document does **not** contain per-module implementation detail. Each module gets its own
brainstorm + spec (see Roadmap). This is the map; the modules are the territory.

> **Supersedes** the earlier draft of this file, which was built from a lossy web summary and
> mis-modelled several features (e.g. treated fee tier as orthogonal to attestation type, and
> matching as rating-only). The authoritative `.md` build guide corrects both.

## Overarching tension: individual vs. organisation attestors (must read)

The build guide is entirely **individual-attestor** (named people, personal credentials,
"Attestor name + credentials" on every badge). A locked project note (2026-06-27) records that
attestation will be **redefined to org-based** — organisations register as attestors —
deferred, "let it be for now."

Sorting by **rework risk** against that pending redefine:

- **Model-agnostic** (survive either model): AMM scoring mechanics, fee tiers, 90/10 split,
  reputation, dispute richness, workspace/rubric/annotations, SLA, settlement, invoicing.
- **Individual-specific** (the verified/badged *entity* changes under an org model): credential
  registry cross-check, verification levels 1–5, "Auracles Certified", CoI declaration of
  personal relationships, the attestor directory's personal-credential display.

The roadmap front-loads model-agnostic subsystems and flags individual-specific items so the
least is wasted if the redefine lands mid-build.

## What already exists (reuse map)

Confirmed in the codebase — the build reuses, not rebuilds, these:

- **Attestation lifecycle skeleton** — `Attestation` (status machine: `pending_fee → matching →
  offered → accepted → report_submitted → released/disputed/...`), `AttestationOffer` cohorts,
  `AttestationDispute`, `AttestationUploadSession`, `AttestorApplication`, `AttestorProfile`,
  `Credential` (`models.py`).
- **AMM cohort mechanics** — top-N cohort offers, atomic first-accept-wins, supersede losers,
  offer expiry, overdue reassignment (`matching_service.py`). The *cohort + first-accept* core
  matches the guide; the **scoring** does not (see Module 3).
- **Escrow + settlement** — `auto_release_attestations` after dispute window
  (`release_service.py`); attestation fee is an escrow transaction type (`financials`).
- **Disputes** — raise / resolve with `release|refund|split` outcomes (`dispute_service.py`),
  escalation timestamps.
- **Credentials** — user-owned, manual admin verification with `verification_url` +
  `reference_number` + `issuer_type` (`credential_service.py`).
- **KYC** — `kyc_status` + document flow (`settings`).
- **Payouts** — `PayoutAccount`, `Payout`, available-balance computation, withdrawal
  (`financials`) — reusable for Attestor wallet + withdrawal.
- **Public badge** — `ExploreAttestationBadge` on framework/contributor (`explore`) — basic, no
  version-lock or full field set.

## Per-module gap analysis

### Module 1 — Attestor Onboarding  *(build priority 1)*

| Capability | Built | Verdict |
|---|---|---|
| 1.1 Application form (name, jurisdiction, specialisations, credentials, LinkedIn, body numbers, CV) | `AttestorApplication` (specializations, jurisdictions, credentials_summary, references, sample_work) | **Partial** — add LinkedIn, body membership numbers, CV upload |
| 1.2 KYC + identity (Stripe Identity), name match, → Level 1 | `kyc_status` flow in settings | **Partial** — reuse KYC; add name-match to credential + level state |
| 1.3 Credential cross-check vs registries (CFA/AICPA/ISACA/RICS/SRA/FCA/ACAMS) → Level 2–3 | Manual admin verify only | **Partial** — registry automation **Missing** (individual-specific) |
| 1.4 CoI declaration (24-mo relationships, annual resubmit) | None | **Missing** |
| 1.5 Sector × Framework-Category taxonomy tags (drive AMM) | Free-text `specializations[]`/`jurisdictions[]` | **Partial** — encode controlled taxonomy tree |
| 1.6 Trial attestation (zero-fee, rubric-scored, 1 retry, 2nd fail → held) | None | **Missing** |
| 1.7 Payout method + tax docs (W-9/W-8BEN), Stripe Connect | `PayoutAccount` exists | **Partial** — reuse; add tax-doc capture |
| 1.8 Profile published → ACTIVE, directory, verification-level badge | `AttestorProfile.active` exists | **Partial** — directory + **verification levels Missing** (individual-specific) |

### Module 2 — Attestation Request Submission  *(build priority 3)*

| Capability | Built | Verdict |
|---|---|---|
| 2.1 Initiate + attestation **type** (Quality/Compliance/Expert/Provenance) | `target_type` (framework/contributor/operator/credential) only | **Partial** — attestation *type* not modelled (≠ target_type) |
| 2.2 Structured Attestation Brief (5 required fields, shown pre-accept) | `summary`/`scope`/`evidence_references` | **Partial** — formalise brief object |
| 2.3 Fee tiers ($500/$1,200/$2,500) + escrow upfront | Single per-target fee + escrow funding | **Partial** — tiers **Missing**; escrow ✅ |
| 2.4 10-business-day SLA from acceptance | `completion_due_at` from `accepted_at`, default **7 calendar** | **Partial** — default + business-day calc |
| 2.5 Read-only Workspace access package (preview vs full, access logging) | None | **Missing** (see Module 4) |

### Module 3 — AMM Matching Engine  *(build priority 2)*

| Capability | Built | Verdict |
|---|---|---|
| 3.1 Conflict screening vs CoI declarations + contributor firm | Excludes requestor + target owner only | **Partial** — declaration-based screening **Missing** |
| 3.2 **Weighted scoring** = Sector .30 + Category .25 + Credential .20 + Availability .15 + Reputation .10; avail cap 5; cold-start 0.5 | Overlap match ordered by `approved_at` FIFO | **Missing — core gap** |
| 3.3 Notify top 3 (type/sector/category/fee$/SLA), anonymised | Cohort offers + notifications | **Partial** — enrich payload |
| 3.4 First-accept-wins, 24–48h window, decline, 2 rounds → 96h refund offer | Atomic accept, supersede, expiry, `needs_admin` | **Partial** — 2-round-then-refund-offer **Missing** |

### Module 4 — Review Workspace  *(build priority 4)* — **largely greenfield**

| Capability | Built | Verdict |
|---|---|---|
| 4.1 Split-screen workspace, access-scoped, all-interactions logged | None | **Missing** |
| 4.2 5–8 dimension **rubric** per type, 1–5 + mandatory comment, weighted overall | None | **Missing** |
| 4.3 Typed **clause-level annotations** (Endorsement/Concern/Caveat/Revision) → report + dispute evidence | None | **Missing** |
| 4.4 **Clarification requests** (max 2, 48h, **SLA pause**) | None | **Missing** |
| 4.5 Overall determination (Approved/Conditional/Not Approved) | `ATTESTATION_OUTCOME_ENUM` ✅ | **Built** |
| 4.6 Structured report template (8 sections, generated from rubric) | `report_key` blob only | **Partial** — structure **Missing** |
| 4.7 Submission quality gate (fields/min-length/prohibited) + 48h grace + late flag | None | **Missing** |

### Module 5 — Delivery, Acceptance & Dispute  *(build priority 5)*

| Capability | Built | Verdict |
|---|---|---|
| 5.1 Report delivery + SLA-status display | Report submit + notifications | **Partial** |
| 5.2 5-business-day dispute window, auto-accept | `dispute_window_ends_at`, default **14 calendar**; `auto_release` ✅ | **Partial** — default + business-day |
| 5.3 Accept → settle + **1–5 rating** + badge publish | Release ✅; rating **Missing**; badge basic | **Partial** |
| 5.4 Dispute **categories** (4) + evidence, vexatious auto-reject, 3-rejected/12mo requestor flag | Free-text reason + resolution types | **Partial** — categories/anti-abuse **Missing** |
| 5.5 Resolution 5 / complex 15 bd; upheld→revise-or-refund + warning; 2nd upheld/12mo→suspension review | Resolve with release/refund/split + escalation ts | **Partial** — revise-resubmit loop, warnings, repeat-offense **Missing** |

### Module 6 — Settlement & Payout  *(build priority 5)*

| Capability | Built | Verdict |
|---|---|---|
| 6.1 Escrow split **90/10** auto on trigger | `platform_commission = 0.00` (attestor 100%) | **Partial — contradiction (money)** |
| 6.2 Payout to wallet, $50 min withdrawal, 1–3 bd, Stripe Connect | `PayoutAccount`/`Payout`/balance ✅ | **Partial** — wire attestor earnings in |
| 6.3 **Version-locked badge** (type/determination/name/creds/date/version), "newer version exists", multi-badge | Basic `ExploreAttestationBadge` | **Partial** — version-lock + fields **Missing** |
| 6.4 Reputation update + **Auracles Certified L5** (10+, ≥4.5) | None | **Missing** (Certified is individual-specific) |
| 6.5 Invoicing (tax invoice + earnings statement + Jan annual summaries) | None | **Missing** |

### Cross-cutting edge cases (guide §"Edge Cases")

- No-accept in 48h → 2nd round → 96h refund offer — **Partial** (`needs_admin` exists, refund-offer flow Missing).
- Accept-then-cannot-complete → revised SLA or void+rematch, 0 fee + flag — **Partial** (`revoke_overdue` reassigns; voluntary-void + flag Missing).
- Post-accept conflict → void + full refund + 0 fee + warning; external discovery → suspension — **Missing**.
- Framework updated → version-locked badge + new request — **Missing** (Module 6.3).

## Decomposition roadmap (one spec → plan → build per module)

Follows the build guide's own priority order. Each is an independent cycle; money + model-agnostic
work precedes individual-specific work to hedge the org-redefine.

1. **Spec A — Module 1 Onboarding.** Application fields, KYC/level state, CoI declaration,
   taxonomy tags, trial calibration, payout/tax, directory + verification levels.
   *(Brainstorm this next.)*
2. **Spec B — Module 3 AMM Scoring.** Replace FIFO with the weighted formula, availability cap,
   reputation input + cold-start, declaration-based conflict screening, 2-round/refund-offer.
3. **Spec C — Module 2 Request + Escrow.** Attestation type, structured brief, fee tiers,
   10-bd SLA, workspace access package handshake. **Money sign-off:** fee tiers.
4. **Spec D — Module 4 Workspace.** Greenfield: split-screen, rubric engine, typed annotations,
   clarifications + SLA pause, structured report, quality gate. Largest cycle.
5. **Spec E — Modules 5 + 6 Delivery/Dispute/Settlement.** Rating, dispute categories + anti-abuse,
   resolution loop, **90/10 split (money sign-off)**, version-locked badges, Certified L5,
   invoicing.

**Money sign-offs required (human):** 90/10 commission default (currently `0.00` — may be a
deliberate founding-class interim), and the launch fee-tier amounts. Setting commission config to
`0` reproduces today's behaviour, so the change is reversible.

## Build standards (apply to every module spec)

- TDD (failing test first), backend-before-frontend, OpenAPI-contract-first.
- All schema changes via additive Alembic migrations; `upgrade`/`downgrade` both tested.
- All money/escrow math inside DB transactions; commission + net == fee asserted; audited.
- RBAC at the dependency layer; PII (rater identity, payout details, CoI entities) never in list
  endpoints; registry fetches to known endpoints only.
- Determinism: AMM scoring must have a stable tie-break so cohort composition is reproducible.

## Open questions / deferred

- **Org-redefine:** if it lands before Specs A/E individual-specific items (registry cross-check,
  verification levels, Certified, directory, personal CoI), re-scope those against org entities.
- **Launch commission rate** (0.10 vs interim 0) and **fee-tier amounts** — architect sign-off.
- **Holiday calendar** for business-day SLA/dispute math — v1 = weekends only; revisit later.
- **Trial-period matchability** (Module 1.6) — matchable for real work during trial, trial-only,
  or unmatchable — decide in Spec A.
- **Workspace framework rendering** (Module 4.1) — how read-only framework content + clause
  anchors are rendered for annotation — decide in Spec D.

## Risks

- **Module 4 scope** — workspace + rubric + annotations is the largest, mostly-greenfield cycle;
  do not bundle with others.
- **Money paths (6.1, 2.3)** — live escrow split + fee changes need human review + a regression
  test proving `commission_rate=0` reproduces current behaviour.
- **Org-redefine rework** — concentrated in Specs A and E individual-specific items; sequencing
  cannot fully remove it, only limit blast radius.
- **AMM determinism** — weighted scoring with ties must remain reproducible; covered by tests.
