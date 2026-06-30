# Attestation Module 2a — Request Submission Reshape (Design)

Version 0.1 · 2026-06-30 · Status: DRAFT (awaiting human review)

## Context

Workflow doc **Module 2 — Attestation Request Submission** (`docs/Auracles Attestation — Product Development Workflow.md` §2.1–2.5) is the source of truth. A working **interim** request flow already exists from the earlier Phase 4b build:

- `app/modules/attestation/service.py::request_attestation` — creates an escrow-funded `Attestation` (status `pending_fee`) + Stripe PaymentIntent.
- `app/modules/financials/escrow_service.py` — `hold/release/refund/split`, already supports `ref_type="attestation"` and `transaction_type="attestation_fee"`.
- The full lifecycle (matching → report → dispute → release) is built downstream and keys off `Attestation.target_type`.

The interim flow is built on a **target_type** dimension (`framework | contributor | operator | credential`) — "attest a thing I own." The workflow doc adds an orthogonal **review-type** dimension (`Quality | Compliance | Expert | Provenance`) — "the lens of review" — plus a structured brief, tiered fees, operator-initiated requests, and a framework access package.

`target_type` is the correct spine of the whole lifecycle and **stays**. Module 2 is therefore an **additive reconciliation**, not a rewrite.

This spec covers **Module 2a** = workflow doc §2.1–2.4 (request shape + fee + SLA). **Module 2b** = §2.5 Framework Access Package, deferred to its own spec (it is large and overlaps the Module 4 Review Workspace).

## Goal

Bring the request-submission surface in line with workflow doc §2.1–2.4: capture a review type and a structured brief, price framework attestations by review-type tier, allow Operators to request attestation on published frameworks they do not own, and align the SLA value to 10 days — all without disturbing the working escrow integration or the downstream lifecycle.

## Out of scope (explicit)

- **§2.5 Framework Access Package** (exec-summary preview, scoped content unlock on accept, access revocation, access logging) → Module 2b.
- Dispute-window value (14 → 5) → belongs to Module 5 (§5.2), not here.
- Any change to matching (Module 3), report (Module 4), dispute (Module 5), or release (Module 6) logic beyond the mechanical fee/SLA-signature and review-type plumbing they consume.
- Business-day vs calendar-day SLA arithmetic. Interim sets `completion_due_at` in calendar days at acceptance; 2a only changes the numeric config (10). Business-day precision is flagged as an open decision, default = keep calendar parity.

## The five deltas (1–4 are in 2a; 5 is 2b)

| # | Delta | Doc | In 2a? |
|---|-------|-----|--------|
| 1 | Review-type dimension | §2.1 | ✅ |
| 2 | Fee tiers + SLA alignment | §2.3, §2.4 | ✅ |
| 3 | Structured brief | §2.2 | ✅ |
| 4 | Operator-initiated requests | §2.1 | ✅ |
| 5 | Framework Access Package | §2.5 | ❌ → 2b |

## Data model changes

All changes are additive and backward-compatible. One Alembic migration.

### New enum: `attestation_review_type_enum`

```
quality | compliance | expert | provenance
```

### `attestations` table — new columns

- `review_type attestation_review_type_enum NULL` — the review lens. NULL allowed for existing interim rows and for non-framework targets where the requestor does not specify one. Required for `target_type = 'framework'` (enforced in the service, not a DB NOT NULL, so historical rows survive).
- `brief JSONB NULL` — the structured brief (delta 3). Shape below. Required for framework targets; optional otherwise.

The existing spare columns `summary` / `scope` / `evidence_references` are **left untouched** (they are populated later in the lifecycle by the report flow). The brief lives in its own column to avoid overloading those.

### Structured brief shape (`brief` JSONB)

Validated by a nested Pydantic model, not raw dict:

```python
class AttestationBrief(BaseModel):
    """Structured review brief shown to the cohort during the offer phase."""
    what_it_does: str        # Field(min_length=1, max_length=2000)
    use_case: str            # Field(min_length=1, max_length=2000) — intended use + audience
    jurisdiction: str        # Field(min_length=1, max_length=200)
    focus_areas: str         # Field(min_length=1, max_length=2000) — specific concerns / review focus
    desired_outcome: str     # Field(min_length=1, max_length=2000) — approval badge / sign-off / endorsement
```

### platform_config seed changes

- **Add** (framework review-tier fees, delta 2):
  - `attestation_fee_review_quality = 500.00`
  - `attestation_fee_review_compliance = 1200.00`
  - `attestation_fee_review_expert = 2500.00`
  - `attestation_fee_review_provenance = 500.00`  *(doc omits Provenance fee — default = Quality tier; flagged)*
- **Change** (SLA alignment, delta 2/§2.4), 7 → 10, all four target types:
  - `attestation_completion_sla_days_framework = 10`
  - `attestation_completion_sla_days_contributor = 10`
  - `attestation_completion_sla_days_operator = 10`
  - `attestation_completion_sla_days_credential = 10`
- **Unchanged**: existing `attestation_fee_{target_type}` keys (250/300/300/100) stay — they price non-framework targets.

Migration `downgrade` restores the SLA values to 7 and removes the new fee keys.

## Service-layer changes (`service.py`)

### Request schema (`AttestationRequestCreateRequest`)

```python
class AttestationRequestCreateRequest(BaseModel):
    target_type: Literal["framework", "contributor", "operator", "credential"]
    target_id: UUID
    review_type: Literal["quality", "compliance", "expert", "provenance"] | None = None
    brief: AttestationBrief | None = None
    requested_specializations: list[str] = Field(min_length=1, max_length=25)
    requested_jurisdictions: list[str] = Field(min_length=1, max_length=25)
```

Service-level rule (not schema-level, because it is conditional on `target_type`):
- `target_type == "framework"` ⇒ `review_type` and `brief` are **required**; missing ⇒ `HTTPException(422)`.
- Other target types ⇒ `review_type`/`brief` optional; if `review_type` is given it is stored (informs matching) but does not change the fee.

### Fee resolution (`_attestation_fee`)

Signature changes from `(db, target_type)` to `(db, target_type, review_type)`.

```
if target_type == "framework":
    require review_type
    key = f"attestation_fee_review_{review_type}"
else:
    key = f"attestation_fee_{target_type}"   # unchanged behaviour
```

`ATTESTATION_FEE_DEFAULTS` gains the four review-tier defaults as a fallback when config is absent (mirrors the existing pattern). Invalid config value ⇒ `HTTPException(500)` (unchanged pattern).

### Target validation (`_validate_attestation_target`) — delta 4

Framework branch is relaxed to support operator-initiated requests:

- If `framework.contributor_id == requestor_id` and framework not deleted → allowed (owner path, any status — owner may attest their own).
- Else (requestor is **not** owner) → allowed **only if** the framework is **published** (`Framework.status == "published"`) and not deleted. Non-published, non-owned framework ⇒ `HTTPException(404)` (deny by default; do not leak existence of unpublished frameworks).
- `credential` / `contributor` / `operator` branches unchanged (owner/self only).

On a non-owner (operator-initiated) request, after the fee is funded the framework owner is notified (reuse the existing notification dispatch pattern; in-app + email). Audit the request with `initiator_is_owner: bool`.

### Duplicate-in-flight guard (`_reject_duplicate_in_flight_request`) — refinement

Key now includes `review_type` so a requestor may run, e.g., Quality and Compliance concurrently on the same framework (doc: "multiple attestations = multiple requests"). Block only a duplicate `(requestor_id, target_type, target_id, review_type)` in an in-flight status. Two different requestors on the same framework remain independently allowed.

### Persistence (`_create_pending_attestation_fee`)

Sets `review_type` and `brief` on the new `Attestation`. Audit metadata gains `review_type` and `initiator_is_owner` (no brief contents in logs — brief may carry sensitive business detail; log presence only).

## Response schema

`AttestationRequestResponse` gains `review_type: str | None` and `brief: dict | None`. The brief is returned to the **requestor** and (later) the assigned attestor only — it is already gated by the existing per-user attestation read checks (`_can_view_attestation`). No brief in list endpoints for non-participants. (List endpoints already scope to participant rows.)

## Security review (per CLAUDE.md mandatory checklist)

1. **Who can call** — `POST /v1/attestations` stays behind the authenticated-user dependency. Operator-initiated path adds a published-framework gate; unpublished + non-owned ⇒ 404 (no existence leak).
2. **Input** — Pydantic everywhere; `brief` is a typed nested model, not a raw dict; review_type is a `Literal`.
3. **Money** — fee resolution change is value-only; the escrow funding path (PaymentIntent → `escrow_service.hold`) is untouched. All writes stay inside the existing owner-transaction (`async with db.begin()`).
4. **PII / secrets** — brief contents never logged or returned in list endpoints; provider_ref logging unchanged (last-4 only).
5. **Audit** — request creation already audited; add `review_type` + `initiator_is_owner`; owner-notification on operator-initiated requests is logged.
6. **Abuse** — duplicate-in-flight guard prevents a requestor spamming identical requests; distinct review-types intentionally allowed.

## Testing (TDD, RED→GREEN per behaviour)

Unit (`tests/unit/modules/test_attestation_service.py`):
- framework request requires review_type + brief (missing ⇒ 422).
- non-framework request: review_type/brief optional; fee unaffected by review_type.
- fee resolution: framework Quality=500, Compliance=1200, Expert=2500, Provenance=500; contributor/operator/credential keep 300/300/100.
- operator-initiated: non-owner on **published** framework ⇒ allowed; non-owner on **unpublished** ⇒ 404; owner on own framework ⇒ allowed.
- duplicate guard: same `(requestor,target,review_type)` in-flight ⇒ 409; different review_type ⇒ allowed; different requestor ⇒ allowed.
- owner notified on operator-initiated request (dispatch asserted).

Integration (`tests/integration/test_attestation_endpoints.py`):
- `POST /attestations` framework happy path returns funding response + persists review_type/brief.
- 422 on framework request missing review_type/brief.
- 404 on operator-initiated request against unpublished framework.
- response/list endpoints expose brief only to participants.

Migration:
- `alembic upgrade head` + `downgrade -1` both succeed; new enum/column added and dropped; SLA seeds flip 7↔10; review-fee keys added/removed.

## Open decisions (defaults chosen; human may veto at review)

1. **Operator-initiated scope** — default: allowed on **published** frameworks, owner notified. (Alt: owner-only, diverges from §2.1.)
2. **Provenance fee** — default: **$500** (= Quality). (Alt: $1,200, or defer Provenance entirely.)
3. **SLA unit** — default: keep interim **calendar-day** arithmetic, value 10; business-day precision deferred. (Doc says "business days".)
4. **Review-type on non-framework targets** — default: stored if provided (informs matching) but does not reprice. (Alt: forbid review_type unless framework.)

## Downstream notes (no change required in 2a, but verified)

- `matching_service._completion_sla_days` and `dispute_service._completion_sla_days` read the SLA config by `target_type`; the 7→10 value change flows through automatically for new acceptances. No signature change.
- `_attestation_fee` is only called from `request_attestation`; signature change is local.
- Matching/AMM consumption of `review_type` (e.g., scoring weight) is **Module 3** work, not 2a. 2a only captures and stores it.
