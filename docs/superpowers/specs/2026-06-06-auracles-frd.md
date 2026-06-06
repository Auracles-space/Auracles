# Auracles — Functional Requirements Document (FRD)

**Version:** 1.0  
**Status:** Draft  
**Date:** 2026-06-06  
**Audience:** Engineering Team  

---

## Change Log

| Version | Date | Author | Notes |
|---|---|---|---|
| 1.0 | 2026-06-06 | — | Initial draft |

---

## 1. Document Purpose

This FRD defines the functional requirements for the Auracles platform — a knowledge marketplace where Contributors publish professional frameworks, Operators license and implement them, and Attestors verify their quality. It is stack-agnostic and intended to drive engineering implementation.

Requirements follow the convention:
- **FR-[MODULE]-NNN** — Functional requirement ("The system shall…")
- **BR-[MODULE]-NNN** — Business rule (constraint or policy governing behaviour)

---

## 2. Shared Data Model

The following entities are referenced across all modules.

### 2.1 Core Entities

| Entity | Key Fields | Notes |
|---|---|---|
| **User** | id, email, password_hash, display_name, avatar_url, bio, location, website, roles[], kyc_status, verified_at, created_at, deactivated_at | Multi-role; one account can hold any combination of Contributor, Operator, Attestor |
| **Role** | type: `contributor \| operator \| attestor \| admin` | Assigned per-user; not mutually exclusive |
| **Framework** | id, contributor_id, title, description, version, status, category, sector, industry, function, tags[], jurisdiction, complexity, org_size, lifecycle_stage, price, currency, license_types[], commercial_rights, usage_restrictions, preview_artifact_id, created_at, published_at | Core marketplace asset |
| **Artifact** | id, framework_id, name, type, file_url, file_size, mime_type, created_at | Files attached to a Framework |
| **License** | id, framework_id, operator_id, type, transaction_id, granted_at, expires_at, status, version_at_grant | Links Operator to purchased Framework |
| **Transaction** | id, payer_id, payee_id, amount, currency, platform_commission, net_amount, type, status, ref_id, ref_type, created_at | Covers purchases, project payments, royalties, attestation fees |
| **Escrow** | id, ref_id, ref_type, amount, currency, status, held_at, released_at, release_conditions[], released_by | `ref_type`: `project_milestone \| attestation`; `status`: `held \| released \| refunded` |
| **Attestation** | id, target_type, target_id, attestor_id, requestor_id, status, findings, outcome, report_url, issued_at, expires_at | `target_type`: `framework \| contributor \| operator \| credential`; `outcome`: `approved \| conditional \| rejected` |
| **Credential** | id, user_id, type, name, issuer, issued_at, expiry_at, verification_url, verified | e.g. PMP, CPA, ISO cert |
| **Project** | id, operator_id, title, description, category, budget_min, budget_max, currency, deadline, status, created_at | `status`: `open \| assigned \| in_progress \| delivered \| closed \| disputed` |
| **Proposal** | id, project_id, contributor_id, scope, budget, currency, timeline_days, deliverables[], status, created_at | `status`: `pending \| accepted \| rejected \| withdrawn` |
| **Milestone** | id, project_id, name, description, budget, currency, due_date, status, escrow_id | `status`: `pending \| funded \| in_progress \| submitted \| approved \| disputed` |
| **Deliverable** | id, milestone_id, contributor_id, name, description, file_urls[], submitted_at, approved_at, status | `status`: `submitted \| approved \| revision_requested` |
| **Review** | id, reviewer_id, target_type, target_id, score, body, created_at, updated_at | `target_type`: `framework \| contributor`; score 1–5 |
| **ReputationScore** | id, subject_id, subject_type, score, components{}, last_calculated_at | `subject_type`: `framework \| contributor \| operator`; components keyed by factor |
| **Notification** | id, user_id, type, payload, read_at, created_at | System events delivered to users |
| **Dispute** | id, project_id, raised_by, reason, status, resolution, admin_id, created_at, resolved_at | `status`: `open \| under_review \| resolved` |
| **PayoutAccount** | id, user_id, type, provider, account_details_encrypted, is_default, verified_at | Contributor-linked bank or payment provider account |
| **Payout** | id, contributor_id, payout_account_id, amount, currency, commission_deducted, net_amount, status, initiated_at, completed_at | `status`: `pending \| processing \| completed \| failed` |

### 2.2 Lifecycle State Machines

**Framework**
```
draft → submitted → under_review → published
                              └──→ rejected (with reason)
published → unpublished
```

**Project**
```
open → assigned → in_progress → delivered → closed
              └──────────────────────────→ disputed → closed
```

**Attestation**
```
requested → assigned → under_review → issued
         └──→ declined (reassigned)        └──→ disputed
```

**License**
```
active → expired
      └──→ revoked
```

**Milestone**
```
pending → funded → in_progress → submitted → approved
                                          └──→ revision_requested → submitted
                                          └──→ disputed
```

---

## 3. Auth & Identity Module

### Purpose
Manages user registration, authentication, role assignment, KYC verification, and session lifecycle.

### Actors
- All users (unauthenticated and authenticated)
- Admin (approval of Attestor role)

### Functional Requirements

| ID | Requirement |
|---|---|
| FR-AUTH-001 | The system shall support user registration via email and password. |
| FR-AUTH-002 | The system shall support OAuth login via Google and LinkedIn. |
| FR-AUTH-003 | The system shall require new users to select at least one role at registration: Contributor, Operator, or Attestor (subject to approval). |
| FR-AUTH-004 | The system shall send a verification email on registration and deny access until the email is confirmed. |
| FR-AUTH-005 | The system shall allow users to add additional roles post-registration. |
| FR-AUTH-006 | The system shall support TOTP-based two-factor authentication (2FA). |
| FR-AUTH-007 | The system shall issue scoped access tokens encoding the user's active roles and permissions. |
| FR-AUTH-008 | The system shall enforce role-based access control on all protected resources. |
| FR-AUTH-009 | The system shall support KYC document submission for Contributors seeking payout access. |
| FR-AUTH-010 | The system shall notify users on successful login from a new device. |
| FR-AUTH-011 | The system shall support password reset via email-based one-time link (expiry: 15 minutes). |

### Business Rules

| ID | Rule |
|---|---|
| BR-AUTH-001 | The Attestor role requires Admin approval; users cannot self-activate it. |
| BR-AUTH-002 | Framework publishing requires KYC-verified Contributor status. |
| BR-AUTH-003 | Sessions expire after 30 days of inactivity. |
| BR-AUTH-004 | 2FA is required for: withdrawal initiation, payment method updates, and account email changes. |

### Error States

| Trigger | Response |
|---|---|
| Duplicate email on registration | `409 Conflict` — "An account with this email already exists." |
| Unverified email on login | `403 Forbidden` — "Please verify your email before logging in." |
| Invalid credentials | `401 Unauthorized` — "Incorrect email or password." |
| Expired reset link | `410 Gone` — "This reset link has expired. Request a new one." |

---

## 4. Explore Module

### Purpose
Powers marketplace discovery — browsing, searching, filtering, and previewing frameworks for authenticated and unauthenticated users.

### Actors
- Operator (primary consumer)
- Contributor (can browse; excluded from own listings)
- Unauthenticated visitors (browse only; cannot purchase or download)

### Functional Requirements

| ID | Requirement |
|---|---|
| FR-EXP-001 | The system shall display a paginated framework catalog (default: 20 per page). |
| FR-EXP-002 | The system shall support sorting by: newest, top-rated, most purchased, and price (asc/desc). |
| FR-EXP-003 | The system shall support full-text search across framework title, description, and tags. |
| FR-EXP-004 | The system shall support faceted filtering by: sector, industry, function, category, license type, complexity, org size, lifecycle stage, jurisdiction, price range, and attestation status. |
| FR-EXP-005 | The system shall display a Framework card showing: title, contributor name, category, price, review score (avg + count), and attestation badge (if attested). |
| FR-EXP-006 | The system shall provide a Framework detail page with: full metadata, artifact list (gated), contributor profile summary, reviews, attestations, and version history. |
| FR-EXP-007 | The system shall display a "preview" artifact on the detail page if the contributor has designated one. |
| FR-EXP-008 | Unauthenticated users shall be able to browse and search but shall be prompted to log in when attempting to view artifact content or purchase. |
| FR-EXP-009 | The system shall surface up to 6 "related frameworks" recommendations on each Framework detail page. |
| FR-EXP-010 | Operators shall be able to save frameworks to a watchlist. |
| FR-EXP-011 | Frameworks the Operator has already licensed shall display an "Owned" badge in place of the purchase CTA. |

### Business Rules

| ID | Rule |
|---|---|
| BR-EXP-001 | Only frameworks in `published` status appear in the catalog. |
| BR-EXP-002 | A Contributor's own frameworks are excluded from their Explore catalog view. |
| BR-EXP-003 | Search and filter results must return within 2 seconds under normal load. |

### Error States

| Trigger | Response |
|---|---|
| Search returns no results | Empty state with "Try broader search terms or remove filters." |
| Framework detail page for unpublished framework | `404 Not Found` |

---

## 5. Frameworks Module

### Purpose
Contributor-facing framework creation, editing, versioning, submission, and analytics. Operator-facing licensed framework library, access, and review.

### Actors
- Contributor (create, manage, publish)
- Operator (access licensed frameworks, review)
- Admin (review and approve/reject submissions)

### Functional Requirements — Contributor

| ID | Requirement |
|---|---|
| FR-FWK-001 | The system shall allow a Contributor to create a Framework with: title, description, category, sector, industry, function, tags, jurisdiction, complexity level, org size, lifecycle stage. |
| FR-FWK-002 | The system shall allow a Contributor to upload one or more Artifacts per Framework (supported types: PDF, DOCX, XLSX, PPTX, ZIP; max 500 MB total per framework). |
| FR-FWK-003 | The system shall allow a Contributor to configure pricing: price, supported license types, commercial rights description, usage restrictions. |
| FR-FWK-004 | The system shall allow a Contributor to designate one Artifact as the "preview" artifact (optional). |
| FR-FWK-005 | The system shall allow a Contributor to save a Framework as `draft` before submission. |
| FR-FWK-006 | The system shall allow a Contributor to submit a Framework for admin review; status transitions to `submitted`. |
| FR-FWK-007 | The system shall notify the Contributor of the review outcome: approved (transitions to `published`) or rejected (with written reason). |
| FR-FWK-008 | The system shall allow a Contributor to create a new version of a published Framework; prior version remains accessible to existing licensees. |
| FR-FWK-009 | The system shall allow a Contributor to unpublish a Framework (halts new sales; existing licenses unaffected). |
| FR-FWK-010 | The system shall display per-framework analytics to the Contributor: total views, purchases, total revenue, average review score. |

### Functional Requirements — Operator

| ID | Requirement |
|---|---|
| FR-FWK-011 | The system shall display a personal library of all Frameworks the Operator has licensed. |
| FR-FWK-012 | The system shall allow an Operator to download Artifacts for any Framework they have licensed. |
| FR-FWK-013 | The system shall notify an Operator when a licensed Framework publishes a new version. |
| FR-FWK-014 | The system shall allow an Operator to submit a Review (score 1–5, written body) for a licensed Framework. |

### Business Rules

| ID | Rule |
|---|---|
| BR-FWK-001 | A Framework must have at least 1 Artifact before it can be submitted for review. |
| BR-FWK-002 | Framework price must be greater than zero. |
| BR-FWK-003 | Modifying Artifacts on a published Framework requires a version increment. |
| BR-FWK-004 | An Operator may only review a Framework they have an active license for. |
| BR-FWK-005 | An Operator may submit one review per Framework; editable within 30 days of submission. |
| BR-FWK-006 | Artifact downloads are logged per license for audit purposes. |

### Error States

| Trigger | Response |
|---|---|
| Upload exceeds 500 MB | `413 Payload Too Large` — "Total artifact size cannot exceed 500 MB." |
| Unsupported file type upload | `415 Unsupported Media Type` — list of allowed types returned. |
| Submit without artifact | `422 Unprocessable Entity` — "Add at least one artifact before submitting." |
| Operator downloads without license | `403 Forbidden` — "You do not have a license for this framework." |

---

## 6. Projects Module

### Purpose
Operators post custom framework creation or customization requests. Contributors bid. Work is executed in a Workspace with milestones, Escrow-backed payments, Deliverables, and Dispute resolution.

### Actors
- Operator (create projects, review proposals, fund milestones, approve deliverables)
- Contributor (browse projects, submit proposals, deliver work)
- Admin (dispute resolution, Escrow override)

### Functional Requirements

| ID | Requirement |
|---|---|
| FR-PROJ-001 | The system shall allow an Operator to create a Project with: title, description, category, budget range, deadline, and list of required deliverables. |
| FR-PROJ-002 | The system shall display open Projects in a marketplace view visible only to authenticated Contributors. |
| FR-PROJ-003 | The system shall allow a Contributor to submit a Proposal against an open Project: scope, fixed budget, timeline (days), and deliverables list. |
| FR-PROJ-004 | The system shall allow the Operator to accept one Proposal; status transitions to `assigned`. |
| FR-PROJ-005 | The system shall create a Workspace upon project assignment, providing: real-time messaging, file sharing, milestone tracker, and deliverables board. |
| FR-PROJ-006 | The system shall allow the Contributor to define Milestones within an assigned Project: name, description, budget, and due date. |
| FR-PROJ-007 | The system shall require the Operator to fund Escrow for a Milestone before the Contributor can begin work on it. |
| FR-PROJ-008 | The system shall allow the Contributor to submit a Deliverable per Milestone. |
| FR-PROJ-009 | The system shall allow the Operator to approve a Deliverable, triggering Escrow release to the Contributor. |
| FR-PROJ-010 | The system shall allow the Operator to request a revision on a Deliverable, with written feedback. |
| FR-PROJ-011 | The system shall allow either party to raise a Dispute on a Milestone, pausing Escrow release. |
| FR-PROJ-012 | The system shall route Disputes to an Admin for resolution. |
| FR-PROJ-013 | The system shall allow a Contributor to optionally publish a completed Project deliverable as a Framework. |

### Business Rules

| ID | Rule |
|---|---|
| BR-PROJ-001 | The Operator must fund Escrow for a Milestone before the Workspace for that Milestone activates. |
| BR-PROJ-002 | A Contributor may not modify scope, budget, or timeline of an accepted Proposal without the Operator's written agreement (amendment flow required). |
| BR-PROJ-003 | A Dispute auto-escalates to Admin if unresolved by both parties within 7 days. |
| BR-PROJ-004 | An Operator may have a maximum of 5 active Projects concurrently at MVP. |
| BR-PROJ-005 | A Project with no Proposal accepted within 30 days auto-closes unless the Operator extends it. |

### Error States

| Trigger | Response |
|---|---|
| Operator approves deliverable without funded Escrow | `409 Conflict` — "Fund this milestone's escrow before approving a deliverable." |
| Contributor submits proposal on own project | `403 Forbidden` — "You cannot bid on your own project." |
| Dispute raised after milestone approved | `422 Unprocessable Entity` — "This milestone has already been approved." |

---

## 7. Attestation Module

### Purpose
Independent Attestors verify Frameworks, Contributor profiles, Operator organizations, and Credentials. Attestations are formal, signed trust signals that enhance Reputation Scores and are displayed publicly.

### Actors
- Attestor (apply, accept assignments, conduct review, issue report)
- Contributor (request attestation on their frameworks or profile)
- Operator (request attestation on their organization)
- Admin (approve Attestor applicants, handle disputes)

### Functional Requirements

| ID | Requirement |
|---|---|
| FR-ATT-001 | The system shall allow a user to apply for the Attestor role by submitting: professional credentials, areas of specialization, jurisdictions, and sample work/references. |
| FR-ATT-002 | The system shall allow an Admin to review Attestor applications and approve or reject with written feedback. |
| FR-ATT-003 | The system shall allow a Contributor or Operator to request an Attestation on a supported target: Framework, Contributor profile, Operator organization, or Credential. |
| FR-ATT-004 | The system shall match an Attestation request to eligible Attestors based on specialization and jurisdiction. |
| FR-ATT-005 | The system shall notify matched Attestors of an available assignment; Attestors have 48 hours to accept or decline. |
| FR-ATT-006 | The system shall reassign the Attestation request if no Attestor accepts within 48 hours. |
| FR-ATT-007 | The system shall allow the assigned Attestor to submit a structured findings report: summary, evidence references, scope, and outcome (Approved / Conditional / Rejected). |
| FR-ATT-008 | The system shall publish the Attestation report on the attested entity's public profile upon submission. |
| FR-ATT-009 | The system shall release Attestor compensation from Escrow upon report submission. |
| FR-ATT-010 | The system shall allow the requestor to dispute an Attestation finding within 14 days of issuance. |
| FR-ATT-011 | The system shall display attestation badges on Framework cards and Contributor profiles in Explore. |

### Business Rules

| ID | Rule |
|---|---|
| BR-ATT-001 | An Attestor may not attest their own Frameworks, profile, or organizations they are affiliated with. |
| BR-ATT-002 | Attestation fee must be paid into Escrow by the requestor before the assignment is issued. |
| BR-ATT-003 | An Attestor must complete an assigned Attestation within the agreed SLA; failure triggers reassignment. |
| BR-ATT-004 | A Framework may hold multiple Attestations from different Attestors. |
| BR-ATT-005 | Attestation status and outcome contribute to the subject's ReputationScore. |

### Error States

| Trigger | Response |
|---|---|
| Attestor requests own framework | `403 Forbidden` — "You cannot attest your own content." |
| Attestation requested without Escrow funded | `402 Payment Required` — "Fund the attestation fee before submitting." |
| No eligible Attestors found for match | Notify requestor; Admin manually assigns or refunds. |

---

## 8. Financials Module

### Purpose
Manages payment processing, Operator billing, Contributor earnings, Escrow lifecycle, payout requests, commission deduction, and financial reporting.

### Actors
- Operator (purchase licenses, fund escrow, view billing history)
- Contributor (view earnings, request payouts, view payout history)
- Admin (configure commission rate, manage Escrow overrides)

### Functional Requirements — Operator Billing

| ID | Requirement |
|---|---|
| FR-FIN-001 | The system shall allow an Operator to purchase a Framework license via card payment. |
| FR-FIN-002 | The system shall allow an Operator to store a payment method for future purchases. |
| FR-FIN-003 | The system shall generate a receipt/invoice for every completed Transaction. |
| FR-FIN-004 | The system shall allow an Operator to view purchase history with downloadable invoices. |
| FR-FIN-005 | The system shall allow an Operator to fund Project Milestone Escrow via stored payment method. |
| FR-FIN-006 | The system shall allow an Operator to fund Attestation fee Escrow. |

### Functional Requirements — Contributor Earnings

| ID | Requirement |
|---|---|
| FR-FIN-007 | The system shall display a Contributor earnings dashboard: total revenue, pending (in Escrow), available (cleared for payout), and per-framework breakdown. |
| FR-FIN-008 | The system shall allow a Contributor to link a payout account (bank account or supported payment provider). |
| FR-FIN-009 | The system shall allow a KYC-verified Contributor to request a payout of available earnings, requiring 2FA confirmation. |
| FR-FIN-010 | The system shall deduct the platform commission from earnings at the point of payout. |
| FR-FIN-011 | The system shall display Contributor payout history with status per payout: `pending \| processing \| completed \| failed`. |

### Functional Requirements — Escrow

| ID | Requirement |
|---|---|
| FR-FIN-012 | The system shall place Project Milestone funds in Escrow on Operator payment and release them to the Contributor on Operator approval of the Deliverable. |
| FR-FIN-013 | The system shall place Attestation fees in Escrow on requestor payment and release them to the Attestor on report submission. |
| FR-FIN-014 | The system shall allow an Admin to manually release or refund Escrow during Dispute resolution. |

### Business Rules

| ID | Rule |
|---|---|
| BR-FIN-001 | Platform commission is deducted at the point of payout, not at the point of sale. |
| BR-FIN-002 | Minimum payout threshold: $50 (Admin-configurable). |
| BR-FIN-003 | KYC verification is required before a Contributor can initiate their first payout. |
| BR-FIN-004 | Framework license refunds are available within 48 hours of purchase, provided no Artifacts have been downloaded. |
| BR-FIN-005 | 2FA is required before processing any payout or modifying payout account details. |

### Error States

| Trigger | Response |
|---|---|
| Payout requested below minimum threshold | `422 Unprocessable Entity` — "Minimum payout is $50." |
| Payout without KYC | `403 Forbidden` — "Complete identity verification before withdrawing earnings." |
| Payout without 2FA | `403 Forbidden` — "Enable two-factor authentication before withdrawing." |
| Refund after download | `422 Unprocessable Entity` — "Refund unavailable: artifacts have been downloaded." |

---

## 9. Settings Module

### Purpose
User profile management, verification status, role configuration, security settings, notification preferences, organization management, and Admin platform controls.

### Actors
- All authenticated users (profile, security, notifications)
- Contributor (professional profile, payout accounts)
- Operator (organization profile, payment methods)
- Admin (user management, platform configuration)

### Functional Requirements

| ID | Requirement |
|---|---|
| FR-SET-001 | The system shall allow any user to update: display name, bio, avatar, location, website, and professional credentials. |
| FR-SET-002 | The system shall allow a Contributor to manage their public profile: specializations, industries served, portfolio links, and verified credentials display. |
| FR-SET-003 | The system shall allow an Operator to manage an organization profile: name, industry, size, and logo. |
| FR-SET-004 | The system shall allow a user to view their KYC verification status and the documents submitted. |
| FR-SET-005 | The system shall allow a user to enable and disable TOTP-based 2FA. |
| FR-SET-006 | The system shall allow Operators to add, update, and remove payment methods. |
| FR-SET-007 | The system shall allow Contributors to add, update, and remove payout accounts. |
| FR-SET-008 | The system shall allow users to configure notification preferences by channel (email, in-app) and by event type. |
| FR-SET-009 | The system shall allow users to view all active sessions and revoke any specific session. |
| FR-SET-010 | The system shall allow users to deactivate their account (soft delete; data retained per retention policy). |
| FR-SET-011 | The system shall allow an Admin to: manage user roles, override KYC status, adjust the platform commission rate, and toggle feature flags. |

### Business Rules

| ID | Rule |
|---|---|
| BR-SET-001 | Email changes require re-verification of the new address and 2FA confirmation. |
| BR-SET-002 | A deactivated Contributor's published Frameworks remain visible in Explore; new purchases are suspended. |
| BR-SET-003 | Only an Admin may override a user's KYC status. |

### Error States

| Trigger | Response |
|---|---|
| Email change without 2FA | `403 Forbidden` — "Confirm with your authenticator app before changing email." |
| Avatar upload exceeds size limit | `413 Payload Too Large` — "Avatar must be under 5 MB." |

---

## 10. Appendices

### 10.1 FR Traceability Matrix

| FR ID | Module | PRD Section | Status |
|---|---|---|---|
| FR-AUTH-001–011 | Auth & Identity | §11 Access Control | Draft |
| FR-EXP-001–011 | Explore | §6 Core Platform Modules | Draft |
| FR-FWK-001–014 | Frameworks | §6, §8, §9 | Draft |
| FR-PROJ-001–013 | Projects | §6 Core Platform Modules | Draft |
| FR-ATT-001–011 | Attestation | §6, §10 Trust Layer | Draft |
| FR-FIN-001–014 | Financials | §6, Economic Layer | Draft |
| FR-SET-001–011 | Settings | §11 Access Control | Draft |

### 10.2 Taxonomy Reference

Framework classification fields follow the Auracles Taxonomy Framework (v1.0):

- **Sector:** Private Equity, Venture Capital, Infrastructure, Real Estate
- **Complexity:** L1 Foundational → L5 Enterprise Grade
- **Org Size:** Startup (1–20), Small Business (21–50), SME (51–250), Mid-Market (251–1,000), Enterprise (1,000+)
- **Lifecycle Stage:** Formation, Early Operations, Growth, Maturity, Optimization, Digital Transformation, Institutionalization, Expansion, Transformation, Exit / Transition, Legacy & Continuity

Full taxonomy defined in: `Auracles Product Specification (1).md`

### 10.3 Error Code Registry

Standard HTTP error codes used across all modules:

| Code | Meaning | Usage |
|---|---|---|
| 400 | Bad Request | Malformed request body or missing required field |
| 401 | Unauthorized | Missing or invalid authentication token |
| 402 | Payment Required | Action requires payment (e.g. unfunded Escrow) |
| 403 | Forbidden | Authenticated but insufficient permissions |
| 404 | Not Found | Resource does not exist or is not visible to caller |
| 409 | Conflict | Duplicate resource or invalid state transition |
| 410 | Gone | Resource existed but is permanently removed (e.g. expired link) |
| 413 | Payload Too Large | File upload exceeds size limit |
| 415 | Unsupported Media Type | File type not permitted |
| 422 | Unprocessable Entity | Valid format but fails business rule validation |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Unhandled system error |

### 10.4 Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| OQ-001 | Platform commission rate | Product | TBD |
| OQ-002 | Supported payout providers (Stripe Connect, Paystack, etc.) | Engineering / Product | TBD |
| OQ-003 | Attestation SLA durations per target type | Product | TBD |
| OQ-004 | Free framework tier (future phase trigger) | Product | TBD |
| OQ-005 | OAuth providers beyond Google and LinkedIn | Product | TBD |

---

*End of Auracles FRD v1.0*
