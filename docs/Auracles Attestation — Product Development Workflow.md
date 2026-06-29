# Auracles Attestation — Product Development Workflow

Version 1.0 · Prepared 29 June 2026 · Confidential

# Overview

This document defines the complete product build specification for the Auracles Attestation system — covering Attestor Onboarding, the Automated Market Maker (AMM) matching engine, the Review Workspace, Delivery & Dispute handling, and Settlement. It is structured as a developer build guide, ordered by implementation priority.

# Core Design Principles

One request \= one Attestor. The first of 3 notified Attestors to accept claims the assignment; the request closes automatically for the other 2\.  
First-accept-wins. No queuing, no shared assignments, no split fees.  
Standard SLA only. All attestations: 10 business days from acceptance. No accelerated tiers at launch.  
Escrow-first. Requestor funds are held in escrow at request submission. Attestor receives 90% on settlement. Auracles retains 10%.  
Multiple attestations \= multiple requests. A Requestor who wants a second independent review submits a new attestation request from scratch.

# Module 1 — Attestor Onboarding

This is a one-time flow completed before an Attestor can receive any assignments. Must be fully built before the platform opens to Contributors.

## 1.1  Application Form

Fields: full legal name, email, jurisdiction, sector specialisations (multi-select from taxonomy), credentials held, LinkedIn URL, professional body membership numbers, CV upload.  
Backend: store as Attestor profile object with status \= PENDING.

## 1.2  KYC \+ Identity Verification

Integrate a KYC provider (Stripe Identity or equivalent). Collect government-issued ID and liveness check. Must match the name on their professional body registration. On pass: status → IDENTITY\_VERIFIED (Level 1).

## 1.3  Credential Cross-Check

Cross-reference submitted credentials against issuing body registries:  
  • CFA charterholders → CFA Institute public registry  
  • CPA → AICPA license lookup or state CPA board  
  • CISA/CISM → ISACA member registry  
  • RICS → RICS membership portal  
  • Solicitors → SRA register (UK) / State Bar (US)  
  • FCA Approved → FCA register  
  • CAMS → ACAMS registry  
All credentials must be active and in good standing. On pass: status → PROFESSIONAL\_VERIFIED (Level 2–3).

## 1.4  Conflict of Interest Declaration

Attestor signs and submits a binding CoI declaration. Fields: list of firms, funds, and individuals they have had financial, advisory, or employment relationships with in the past 24 months. Stored in the Attestor profile for automated conflict screening at assignment time. Attestor must re-submit annually.

## 1.5  Sector & Framework Taxonomy Tags

Attestor selects their specialisation tags from the Auracles taxonomy tree: Sector (PE, VC, Infrastructure, Real Estate) × Framework Category (Compliance, Governance, Risk, Operations, Legal, Finance, HR, Technology, Investment Management). These tags are the primary input to the AMM scoring engine. Over-tagging is detectable via quality reviews — persistent over-tagging penalises AMM score.

## 1.6  Trial Attestation

Before going live, the Attestor completes one calibration attestation on a seeded or volunteer Framework at zero fee. Auracles reviews the submitted report against the quality rubric. Pass \= proceed. Fail \= specific feedback provided; one retry allowed. A second fail means the application is held pending further review.

## 1.7  Payout Method Setup

Attestor connects their payout account: bank transfer, wire, or stablecoin wallet. Integrate Stripe Connect (or equivalent). Collect tax documentation: W-9 (US), W-8BEN (non-US), or local equivalent. Required before profile goes live.

## 1.8  Profile Published

On full completion: Attestor profile status → ACTIVE. Profile visible in the Attestor directory. Displays: name, credentials, sector tags, verification level badge, reputation score (initially blank), number of completed attestations. AMM engine begins including this Attestor in future match scoring runs.

# Module 2 — Attestation Request Submission

Triggered by a Contributor or Operator from the Framework page or the Attest module dashboard.

## 2.1  Initiate Request

Entry point: "Request Attestation" button on the Framework page (Operator view) or Attest dashboard (Contributor view).  
Requestor selects attestation type:  
  • Quality Review — framework completeness, accuracy, and implementability  
  • Compliance Review — regulatory alignment for stated jurisdiction  
  • Expert Attestation — subject-matter accuracy by a domain specialist  
  • Provenance Attestation — IP ownership and authorship verification

## 2.2  Attestation Brief

Requestor completes a structured brief. Required fields: (a) what the Framework does, (b) intended use case and audience, (c) target jurisdiction, (d) specific concerns or review focus areas, (e) desired outcome (approval badge, compliance sign-off, expert endorsement). The brief is shown to matched Attestors during the preview phase before they accept. Store brief as a document object linked to the attestation request.

## 2.3  Fee & Escrow

Platform suggests a fee tier based on framework complexity and attestation type. Standard tiers:  
  • Quality Review: $500  
  • Compliance Review: $1,200  
  • Expert Attestation: $2,500  
Requestor pays upfront. Full fee held in escrow immediately (Stripe Escrow or equivalent). No charge to Attestors. No payout until settlement trigger. Attestation request status \= PENDING\_MATCH.

## 2.4  SLA

All attestations: 10 business day SLA. Clock starts from the moment an Attestor accepts the assignment — not from request submission. Display SLA deadline clearly to both Requestor and Attestor in the workspace.

## 2.5  Framework Access Package

Platform creates a secure, read-only Attestation Workspace. Package contents: framework title, category, industry metadata, a 1-page executive summary (for preview), and full framework content (unlocked only after acceptance). Framework content access is scoped to the assigned Attestor only, and is revoked when the attestation is finalised. Log all access events for audit trail.

# Module 3 — AMM Matching Engine

Runs automatically within minutes of escrow confirmation. This is the core algorithmic layer.

## 3.1  Conflict Screening

Before scoring, cross-reference every active Attestor's CoI declaration against: the Contributor's profile, the Contributor's firm/organisation name, and any declared relationships in the Attestor's history. Conflicted Attestors are excluded from the match pool for this specific request. Log exclusions.

## 3.2  AMM Scoring

Score each eligible Attestor against the request using this weighted formula:

  Match Score \= (Sector Alignment × 0.30) \+ (Framework Category Match × 0.25) \+ (Credential Relevance × 0.20) \+ (Availability Score × 0.15) \+ (Reputation Score × 0.10)

Availability Score: 1.0 \= no active assignments; 0.0 \= at configurable cap (e.g. 5 concurrent). Attestors at cap are excluded from the pool entirely. Reputation Score: weighted average of Requestor ratings across prior completed attestations (blank profile \= 0.5 baseline to avoid cold-start penalisation).

## 3.3  Notification Dispatch

Top 3 Attestors by score are notified simultaneously via in-app notification \+ email. Notification content: attestation type, sector, framework category, their 90% fee share (displayed as a dollar amount), estimated framework length/complexity, SLA deadline. The notification does NOT reveal who the other 2 notified Attestors are.

## 3.4  First-Accept-Wins Logic

Acceptance window: 24–48 hours from notification send.  
When an Attestor clicks Accept:  
  1\. Their status on this request → ACCEPTED  
  2\. Request status → ASSIGNED  
  3\. Platform immediately sends "Request Claimed" notification to the other 2 Attestors  
  4\. Other 2 Attestors' preview access is revoked  
  5\. Full framework content is unlocked for the accepting Attestor  
  6\. Requestor receives notification: "Your attestation has been accepted by \[Attestor Name\]. Deadline: \[SLA date\]"  
If an Attestor Declines: removed from this request's pool; remaining Attestors' window stays open.  
If no Attestor responds within 48 hours: all 3 auto-declined; AMM runs a fresh scoring cycle with next ranked candidates. Requestor notified of delay. If no acceptance after two consecutive rounds (96 hours total), Requestor is offered full escrow refund or option to keep request open.

# Module 4 — Review Workspace

The Attestor's working environment for the duration of the review.

## 4.1  Workspace Layout

Split-screen interface:  
  • Left panel: framework content viewer (read-only). Clause-level annotation capability.  
  • Right panel: structured finding form (rubric dimensions \+ report builder).  
All interactions logged with timestamps for audit trail. Access restricted to the assigned Attestor only.

## 4.2  Review Rubric

Each attestation type has a 5–8 dimension rubric. Attestor scores each dimension. Example for Quality Review: Completeness, Implementability, Accuracy, Clarity, Version Currency, Appropriate Scope, Risk Flags, Recommended Use Cases. Each dimension: 1–5 score \+ mandatory comment field. An overall weighted score is calculated automatically.

## 4.3  Clause-Level Annotations

Attestor can attach annotations directly to individual clauses or sections of the framework. Annotations are typed: Endorsement, Concern, Jurisdictional Caveat, Revision Recommended. These annotations are included in the final published attestation report and serve as the primary evidence base in any dispute.

## 4.4  Clarification Requests

If the Attestor has a material question about scope, jurisdiction, or intent, they may submit a clarification request to the Requestor via the platform workspace (not direct email). Requestor has 48 hours to respond. SLA clock is paused from the time the clarification is sent until the response is received. Maximum 2 clarification requests per assignment to prevent scope creep.

## 4.5  Overall Determination

Attestor selects one outcome:  
  • Approved — framework meets the standards of the attestation type with no material issues.  
  • Approved with Conditions — framework is sound but specific named areas require revision before the attestation is treated as unconditional.  
  • Not Approved — framework has material issues that must be resolved before an attestation can be issued.

## 4.6  Attestation Report

Attestor completes the structured report using the Auracles standardised template. Sections: (a) Executive Summary, (b) Scope of Review, (c) Methodology, (d) Dimension Scores, (e) Key Findings, (f) Conditions (if any), (g) Overall Determination, (h) Attestor name, credentials, and verification level. Report is generated from the rubric data — not a freeform document. Attestor may add supplementary notes but the structured sections are mandatory.

## 4.7  Submission & Quality Gate

Attestor submits the report. Submission is final — no edits after submission except via dispute process. Platform runs an automated quality gate: (a) all mandatory rubric fields complete, (b) report length meets minimum word threshold, (c) no prohibited content. Pass → report delivered to Requestor. Fail → Attestor receives specific rejection with required revisions; 48-hour grace period to fix. Late submission (after SLA \+ 24hr grace) triggers a late flag on the Attestor's profile.

# Module 5 — Delivery, Acceptance & Dispute

Post-submission handling on the Requestor side.

## 5.1  Report Delivery

Requestor receives in-app notification \+ email on report submission. Full report accessible in their Attest dashboard. One report from one Attestor — clean, single-source output. SLA compliance status shown (on time / late).

## 5.2  5-Day Dispute Window

A 5-business-day countdown begins on report delivery. Options available to Requestor during this window: Accept or Dispute. If no action is taken within 5 days, the report is auto-accepted and settlement is triggered automatically.

## 5.3  Accept

Requestor clicks "Accept Report". Settlement triggered immediately. Requestor is prompted to rate the attestation quality: 1–5 stars \+ optional written comment. Rating feeds directly into the Attestor's AMM reputation score. Attestation badge published to the Framework page.

## 5.4  Dispute

Requestor selects "Dispute Report" and must choose a category and provide written evidence:  
  • Scope Error — Attestor reviewed the wrong version or misunderstood scope  
  • Process Violation — Attestor did not follow the stated methodology  
  • Material Inaccuracy — specific factual errors in the findings  
  • Conflict of Interest — Requestor has new evidence of an undisclosed conflict  
Escrow is frozen during the dispute. Vexatious disputes (no evidence provided) are rejected by the platform automatically. Three rejected disputes within 12 months \= Requestor flag visible to Attestors at match time.

## 5.5  Dispute Resolution

Platform team reviews: Requestor's dispute submission, Attestor's original report, workspace audit trail, clarification logs. Standard resolution: 5 business days. Complex cases: up to 15 business days. Outcomes:  
  • Upheld: Attestor revises and resubmits (Scope Error / Material Inaccuracy) OR full refund to Requestor (Conflict of Interest). Attestor receives a formal warning. Second upheld dispute within 12 months triggers suspension review.  
  • Rejected: Escrow released to Attestor. Report stands and is published. Requestor cannot raise a second dispute on the same report.  
If Requestor wants a second independent opinion after a rejected dispute: submit a new attestation request.

# Module 6 — Settlement & Payout

Triggered by: Requestor acceptance, auto-acceptance after 5-day window, or dispute rejection.

## 6.1  Escrow Release

Escrow split on settlement trigger:  
  • 90% → Attestor wallet (immediate)  
  • 10% → Auracles treasury  
No manual processing. Fully automated.

## 6.2  Attestor Payout

90% share lands in Attestor's in-platform wallet. Attestor can request withdrawal to their configured bank/wire/stablecoin account at any time above the minimum withdrawal threshold ($50). Withdrawal processed within 1–3 business days via Stripe Connect or equivalent.

## 6.3  Attestation Badge Published

Attestation badge permanently published on the Framework page. Badge displays: attestation type, determination (Approved / Approved with Conditions / Not Approved), Attestor name, credentials, date, and framework version. Visible to all users who view the framework. Logged in the Attestor's public profile under "Completed Attestations". Provenance record updated.

## 6.4  Reputation Update

Requestor's star rating (submitted at 5.3) is processed into Attestor's reputation score. Score is used in all subsequent AMM match scoring runs. Eligibility for Auracles Certified Attestor status (Verification Level 5): 10+ completed attestations with ≥ 4.5/5.0 average rating.

## 6.5  Invoicing

Tax invoice auto-generated for the Requestor (full fee). Earnings statement auto-generated for the Attestor (90% share). Both documents stored in the Financials module. Annual earnings summaries generated each January for tax purposes.

# Edge Cases & Platform Rules

No Attestors accept within 48hrs: AMM runs a second round with the next top 3 candidates. Requestor notified of delay. After two consecutive failed rounds (96hrs), Requestor offered full refund or option to keep request open.

Attestor accepts then cannot complete: Attestor notifies platform. Requestor offered: (a) revised SLA with same Attestor, or (b) void and re-match. If voided, new Attestor starts fresh. Original Attestor receives 0 fee and a late-completion flag.

Conflict discovered after acceptance: Attestor self-declares immediately. Assignment voided. Full escrow refund. Attestor receives 0 fee and a formal warning. Undisclosed conflict discovered externally \= immediate suspension pending review.

Requestor wants a second attestation: Submit a new attestation request. Same process, new brief, new fee, new AMM match cycle. Both badges display on the Framework page independently.

Framework substantially updated after attestation: Badge is version-locked (e.g., "Attested: v1.2"). New version requires a new attestation request. Prior version badge remains with a notice: "A newer version of this framework exists."

# Fee Reference

Quality Review: $500 total · Attestor receives $450 · Auracles $50 · SLA 10 business days  
Compliance Review: $1,200 total · Attestor receives $1,080 · Auracles $120 · SLA 10 business days  
Expert Attestation: $2,500 total · Attestor receives $2,250 · Auracles $250 · SLA 10 business days

# Build Priority Order

1\. Attestor Onboarding (Module 1\) — must be complete before any public launch activity  
2\. AMM Matching Engine (Module 3\) — core infrastructure; everything downstream depends on it  
3\. Request Submission & Escrow (Module 2\) — Requestor-facing flow and payment  
4\. Review Workspace (Module 4\) — Attestor working environment  
5\. Delivery, Dispute & Settlement (Modules 5–6) — completion loop

Prepared by Eragon AI for Auracles · 29 June 2026  
