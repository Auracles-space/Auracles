# Attestation Module 6a — Settlement & Payout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settle attestation earnings at 90/10 (10% platform commission) with immediate clearance, drawn through the existing contributor payout infrastructure.

**Architecture:** Backend-only, extends `app/modules/financials/service.py` in place. The escrow release path (Module 5) is unchanged; the "90/10 split" is a commission applied at the payout-balance layer. `_available_payout_balance` is refactored to compute two earning classes — *marketplace* (framework/project, 15%, refund-window clearance — byte-identical to today) and *attestation* (`attestation_fee`, 10%, immediate clearance) — then combine them. `EarningsResponse.commission_rate` becomes the effective blended rate. No migration, no escrow change, no new endpoint, no new table.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, PostgreSQL 16, pytest + pytest-asyncio, httpx AsyncClient, freezegun, pyotp, `uv`. All commands run from `backend/`.

## Global Constraints

- No Alembic migration, no escrow-path change, no new endpoint, no new table (spec §10).
- New commission rate read from `platform_config` with an **in-code default** `Decimal("0.10")` — mirrors `_commission_rate` (default `Decimal("0.15")`); **no seed row required**.
- All money amounts quantized to 2dp via the existing `_normalise_money` helper.
- `EarningsResponse.commission_rate` = effective blended rate across cleared earnings; `0` when there are no cleared earnings (no division by zero).
- Framework/project payout behavior is **byte-identical** to today, including the serialized `commission_rate` string `"0.15"` (regression-guarded by existing tests).
- Logging via `loguru` only; no `print`; no bare `except`; typed `HTTPException`s only.
- TDD: RED → GREEN per behavior, one behavior at a time.
- Before declaring any task done: `uv run ruff check .` and `uv run mypy app` from `backend/` must pass (CI lints tests too).
- Run tests from `backend/`: `uv run pytest <path> -v`.

---

### Task 1: Split payout-balance derivation into marketplace (15%) and attestation (10%) classes

**Files:**
- Modify: `backend/app/modules/financials/service.py`
  - add `_attestation_commission_rate` (after `_commission_rate`, ~line 165)
  - add module-level earning-class constants + `_blended_commission_rate` helper
  - refactor `_sum_transactions` (~line 175) to take an `earning_class` parameter
  - refactor `_available_payout_balance` (~line 236)
- Test: `backend/tests/integration/test_financials_payouts.py`
  - update `test_released_attestation_fees_are_withdrawable_earnings` (~line 467)
  - add `test_attestation_earnings_clear_immediately`
  - add `test_mixed_marketplace_and_attestation_earnings_blend_commission`

**Interfaces:**
- Consumes: existing `_normalise_money(Decimal) -> Decimal`, `_commission_rate(db) -> Decimal`, `_refund_window_hours(db) -> int`, `_platform_decimal_config(db, *, key, default) -> Decimal`, `_claimed_payouts(db, *, contributor_id, currency) -> Decimal`, `Transaction`, `Escrow` models, `exists`, `or_`, `func`, `select`.
- Produces:
  - `_attestation_commission_rate(db: AsyncSession) -> Decimal` (default `0.10`)
  - `_MARKETPLACE_EARNING_CLASS = "marketplace"`, `_ATTESTATION_EARNING_CLASS = "attestation"`
  - `_sum_transactions(db, *, contributor_id: UUID, currency: str, earning_class: str, before: datetime | None = None, after_or_at: datetime | None = None) -> Decimal`
  - `_blended_commission_rate(cleared_gross: Decimal, cleared_net: Decimal) -> Decimal`
  - `_available_payout_balance(...)` unchanged 5-tuple signature `(gross_revenue, pending_clearance, available, claimed, commission_rate)` — 5th element now the blended rate. Consumed by `get_contributor_earnings` (~1260) and `request_payout` (~1331), both of which keep working unchanged.

**Context:** Today `_sum_transactions` lumps `purchase` + `milestone` + `attestation_fee` into one `or_(...)` block, and `_available_payout_balance` applies a single flat 15% rate with a single refund-window cutoff to all of them. That means attestors currently settle at 85% and wait the refund window — both wrong per the spec. This task separates the two earning classes.

- [ ] **Step 1: Update the existing attestation-earnings test to the 90/10 expectation (RED)**

In `backend/tests/integration/test_financials_payouts.py`, in `test_released_attestation_fees_are_withdrawable_earnings` (~line 467), change the asserted JSON body from the old 85%/0.15 values to the new 90%/0.10 values. The seeding (600 released + 200 held) is unchanged.

```python
    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "gross_revenue": "600.00",
        "pending_clearance": "0.00",
        "available_balance": "540.00",
        "commission_rate": "0.1",
        "minimum_payout": "50.00",
    }
```

- [ ] **Step 2: Run it to confirm it fails (RED)**

Run: `uv run pytest tests/integration/test_financials_payouts.py::test_released_attestation_fees_are_withdrawable_earnings -v`
Expected: FAIL — current code returns `"available_balance": "510.00"` and `"commission_rate": "0.15"`.

- [ ] **Step 3: Add the attestation commission-rate loader and helpers**

In `backend/app/modules/financials/service.py`, add immediately after `_commission_rate` (~line 165):

```python
async def _attestation_commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured Attestation settlement commission rate.

    Attestation earnings settle at a lower platform commission than the
    framework marketplace (10% vs 15%); see Module 6a design §4.1.
    """
    return await _platform_decimal_config(
        db,
        key="attestation_commission_rate",
        default=Decimal("0.10"),
    )
```

Add these module-level constants near the top of the module (with the other module-level constants, e.g. beside `INVOICE_URL_TTL_SECONDS`):

```python
# Earning classes for payout-balance derivation. Marketplace earnings clear
# after the refund window at the marketplace commission rate; attestation
# earnings clear immediately at the attestation commission rate (Module 6a).
_MARKETPLACE_EARNING_CLASS = "marketplace"
_ATTESTATION_EARNING_CLASS = "attestation"
```

Add this helper directly above `_available_payout_balance`:

```python
def _blended_commission_rate(
    cleared_gross: Decimal, cleared_net: Decimal
) -> Decimal:
    """Return the effective commission rate across cleared earnings.

    Returns 0 when there are no cleared earnings, avoiding division by zero.
    Framework/project-only earners resolve to exactly the marketplace rate,
    attestation-only earners to the attestation rate, and mixed earners to a
    blended rate. Trailing zeros are stripped so a pure 15% earner serializes
    as ``"0.15"`` rather than ``"0.1500"``.
    """
    if cleared_gross <= 0:
        return Decimal("0")
    rate = (Decimal("1") - (cleared_net / cleared_gross)).quantize(Decimal("0.0001"))
    return rate.normalize()
```

- [ ] **Step 4: Refactor `_sum_transactions` to take an `earning_class`**

Replace the whole `_sum_transactions` function with:

```python
async def _sum_transactions(
    db: AsyncSession,
    *,
    contributor_id: UUID,
    currency: str,
    earning_class: str,
    before: datetime | None = None,
    after_or_at: datetime | None = None,
) -> Decimal:
    """Return gross completed earnings for one earning class.

    ``earning_class`` selects which transaction types count:
    ``_MARKETPLACE_EARNING_CLASS`` covers framework purchases and released
    project milestones; ``_ATTESTATION_EARNING_CLASS`` covers released
    attestation fees.
    """
    released_escrow_exists = exists(
        select(Escrow.id).where(
            Escrow.ref_id == Transaction.ref_id,
            Escrow.ref_type == Transaction.ref_type,
            Escrow.status == "released",
        )
    )
    if earning_class == _ATTESTATION_EARNING_CLASS:
        class_filter = (
            (Transaction.transaction_type == "attestation_fee")
            & (Transaction.ref_type == "attestation")
            & released_escrow_exists
        )
    else:
        class_filter = or_(
            Transaction.transaction_type == "purchase",
            (
                (Transaction.transaction_type == "milestone")
                & (Transaction.ref_type == "project_milestone")
                & released_escrow_exists
            ),
        )
    filters = [
        Transaction.payee_id == contributor_id,
        class_filter,
        Transaction.status == "completed",
        Transaction.currency == currency,
    ]
    if before is not None:
        filters.append(Transaction.created_at < before)
    if after_or_at is not None:
        filters.append(Transaction.created_at >= after_or_at)
    value = await db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(*filters)
    )
    return _normalise_money(Decimal(value or "0"))
```

- [ ] **Step 5: Refactor `_available_payout_balance` to combine the two classes**

Replace the whole `_available_payout_balance` function with:

```python
async def _available_payout_balance(
    db: AsyncSession,
    *,
    contributor_id: UUID,
    currency: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return gross, pending, available, claimed, and blended-commission balances.

    Marketplace earnings (framework purchases, released project milestones)
    clear after the refund window at the marketplace commission rate.
    Attestation earnings clear immediately on release at the attestation
    commission rate. The returned commission rate is the effective blended
    rate across all cleared earnings (Module 6a design §5, §6).
    """
    refund_window_hours = await _refund_window_hours(db)
    marketplace_rate = await _commission_rate(db)
    attestation_rate = await _attestation_commission_rate(db)
    cutoff = datetime.now(UTC) - timedelta(hours=refund_window_hours)

    marketplace_gross = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
    )
    marketplace_pending = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
        after_or_at=cutoff,
    )
    marketplace_cleared_gross = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
        before=cutoff,
    )
    # Attestation earnings clear immediately on release — no refund window.
    attestation_gross = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_ATTESTATION_EARNING_CLASS,
    )

    marketplace_cleared_net = _normalise_money(
        marketplace_cleared_gross * (Decimal("1") - marketplace_rate)
    )
    attestation_cleared_net = _normalise_money(
        attestation_gross * (Decimal("1") - attestation_rate)
    )
    claimed = await _claimed_payouts(
        db,
        contributor_id=contributor_id,
        currency=currency,
    )

    total_cleared_gross = marketplace_cleared_gross + attestation_gross
    total_cleared_net = marketplace_cleared_net + attestation_cleared_net
    available = max(_normalise_money(total_cleared_net - claimed), Decimal("0.00"))
    gross_revenue = marketplace_gross + attestation_gross
    pending_clearance = marketplace_pending
    commission_rate = _blended_commission_rate(total_cleared_gross, total_cleared_net)
    return gross_revenue, pending_clearance, available, claimed, commission_rate
```

- [ ] **Step 6: Run the updated attestation test to confirm it passes (GREEN)**

Run: `uv run pytest tests/integration/test_financials_payouts.py::test_released_attestation_fees_are_withdrawable_earnings -v`
Expected: PASS.

- [ ] **Step 7: Confirm framework/project regression tests still pass byte-identically**

Run: `uv run pytest tests/integration/test_financials_payouts.py::test_contributor_earnings_are_refund_window_and_payout_aware tests/integration/test_financials_payouts.py::test_released_project_milestones_are_withdrawable_earnings -v`
Expected: PASS — both still assert `"commission_rate": "0.15"` and their existing `available_balance` values (`75.00`, `765.00`). (Framework-only cleared earnings blend to exactly `0.15`.)

- [ ] **Step 8: Add the immediate-clearance test (RED then GREEN)**

Add to `backend/tests/integration/test_financials_payouts.py`:

```python
async def test_attestation_earnings_clear_immediately(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """Released Attestation earnings are withdrawable at once, with no refund-window wait.

    Enforces Module 6a design §4.2: attestation has already passed its
    dispute window before release, so earnings do not sit in pending
    clearance the way framework sales do.
    """
    del migrated_database, payout_context
    attestor_id, _ = await create_user_with_roles(
        "attestation-immediate@auracles.space",
        ["contributor", "attestor"],
    )
    await create_released_attestation_fee_earning(
        attestor_id,
        amount=Decimal("600.00"),
        created_at=datetime.now(UTC),
    )

    response = await client.get(
        "/v1/financials/earnings",
        headers=auth_headers(attestor_id, ["contributor", "attestor"]),
    )

    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "gross_revenue": "600.00",
        "pending_clearance": "0.00",
        "available_balance": "540.00",
        "commission_rate": "0.1",
        "minimum_payout": "50.00",
    }
```

Run: `uv run pytest tests/integration/test_financials_payouts.py::test_attestation_earnings_clear_immediately -v`
Expected: PASS. (Before the Task 1 code change this would have failed — a just-released attestation would sit in pending clearance and `available_balance` would be `0.00`. Confirm your GREEN by reasoning: the refactor moved attestation out of the cutoff-gated class.)

- [ ] **Step 9: Add the blended-commission mixed-earner test**

Add to `backend/tests/integration/test_financials_payouts.py`:

```python
async def test_mixed_marketplace_and_attestation_earnings_blend_commission(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """A user earning from both frameworks and attestations gets a blended rate.

    Framework earnings settle at 15%, attestation earnings at 10%; the
    reported commission_rate is the effective blend across cleared earnings
    (Module 6a design §6).
    """
    del migrated_database, payout_context
    user_id, _ = await create_user_with_roles(
        "mixed-earnings@auracles.space",
        ["contributor", "attestor"],
    )
    await create_sale(
        user_id,
        amount=Decimal("100.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    await create_released_attestation_fee_earning(
        user_id,
        amount=Decimal("200.00"),
        created_at=datetime.now(UTC),
    )

    response = await client.get(
        "/v1/financials/earnings",
        headers=auth_headers(user_id, ["contributor", "attestor"]),
    )

    assert response.status_code == 200
    # cleared net = 100*0.85 + 200*0.90 = 85.00 + 180.00 = 265.00
    # blended rate = 1 - 265/300 = 0.1167
    assert response.json() == {
        "currency": "USD",
        "gross_revenue": "300.00",
        "pending_clearance": "0.00",
        "available_balance": "265.00",
        "commission_rate": "0.1167",
        "minimum_payout": "50.00",
    }
```

Run: `uv run pytest tests/integration/test_financials_payouts.py::test_mixed_marketplace_and_attestation_earnings_blend_commission -v`
Expected: PASS.

- [ ] **Step 10: Run the full payouts test module + lint + type-check**

Run: `uv run pytest tests/integration/test_financials_payouts.py -v`
Expected: all PASS.
Run: `uv run ruff check .`
Expected: `All checks passed!`
Run: `uv run mypy app`
Expected: no errors.

- [ ] **Step 11: Commit**

```bash
git add app/modules/financials/service.py tests/integration/test_financials_payouts.py
git commit -m "Settle attestation earnings at 90/10 with immediate clearance"
```

---

### Task 2: Attestor withdraws attestation earnings through the existing payout flow

**Files:**
- Test: `backend/tests/integration/test_financials_payouts.py`
  - add `test_attestor_withdraws_attestation_earnings_at_ten_percent_gross_up`

**Interfaces:**
- Consumes: Task 1's blended `commission_rate` (0.10 for an attestation-only earner) via `_available_payout_balance`, which `request_payout` (~line 1331) uses to gross up the payout: `gross_drawdown = _normalise_money(requested_net / (1 - commission_rate))`. Also consumes existing test helpers `create_user_with_roles`, `create_verified_payout_account`, `create_released_attestation_fee_earning`, `auth_headers`, and the `payout_context` fixture.
- Produces: nothing consumed downstream — this is a spec-coverage / integration verification task (design §9 tests 7–8) proving the reused withdrawal path settles attestation earnings correctly. No production code change is expected; if this test fails, the failure indicates a real gap in Task 1.

**Context:** The payout request path is fully built and reused unchanged. It gross-ups the net request by the effective commission rate to record `amount` (gross) and `commission_deducted` on the `Payout` row; solvency is enforced by comparing `requested_net` against net `available` and by claiming `net_amount`. For an attestation-only earner the effective rate is 0.10, so a net-$100 request grosses up to $111.11 (commission $11.11) — distinct from the 0.15 marketplace gross-up ($117.65), which is what makes this test meaningful.

- [ ] **Step 1: Write the withdrawal test (RED against pre-Task-1 code, GREEN after)**

Add to `backend/tests/integration/test_financials_payouts.py`:

```python
async def test_attestor_withdraws_attestation_earnings_at_ten_percent_gross_up(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """An Attestor withdraws attestation earnings; gross-up uses the 10% rate.

    Enforces Module 6a design §9 tests 7-8: attestation earnings are
    withdrawable via the existing KYC/2FA/$50-minimum payout path, and the
    payout's commission bookkeeping reflects the 10% attestation rate.
    """
    del migrated_database
    attestor_id, totp_secret = await create_user_with_roles(
        "attestor-withdraw@auracles.space",
        ["contributor", "attestor"],
    )
    payout_account_id = await create_verified_payout_account(attestor_id)
    await create_released_attestation_fee_earning(
        attestor_id,
        amount=Decimal("600.00"),
        created_at=datetime.now(UTC),
    )
    assert totp_secret is not None
    code = pyotp.TOTP(totp_secret).now()

    response = await client.post(
        "/v1/financials/payouts",
        headers=auth_headers(attestor_id, ["contributor", "attestor"]),
        json={
            "amount": "100.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
            "totp_code": code,
        },
    )

    async with async_session_factory() as session:
        payout = await session.scalar(select(Payout))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["net_amount"] == "100.00"
    # gross-up at 10%: 100 / 0.90 = 111.11, commission = 11.11
    assert body["commission_deducted"] == "11.11"
    assert payout is not None
    assert payout.amount == Decimal("111.11")
    assert payout.net_amount == Decimal("100.00")
```

- [ ] **Step 2: Run it to confirm it passes (GREEN)**

Run: `uv run pytest tests/integration/test_financials_payouts.py::test_attestor_withdraws_attestation_earnings_at_ten_percent_gross_up -v`
Expected: PASS. (Sanity note: before Task 1, this would fail — the attestation earning would be in pending clearance with `available_balance` `0.00`, so the request would be rejected with 422 "exceeds available balance".)

- [ ] **Step 3: Run the full payouts module + lint + type-check**

Run: `uv run pytest tests/integration/test_financials_payouts.py -v`
Expected: all PASS.
Run: `uv run ruff check .`
Expected: `All checks passed!`
Run: `uv run mypy app`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_financials_payouts.py
git commit -m "Verify attestor withdrawal of attestation earnings at 10% gross-up"
```

---

## Self-Review

**Spec coverage:**
- §4.1 (10% commission, config default, no seed) → Task 1 Step 3 (`_attestation_commission_rate`).
- §4.2 (immediate clearance) → Task 1 Steps 5, 8.
- §5 (two-class derivation, marketplace byte-identical) → Task 1 Steps 4, 5, 7.
- §6 (blended effective rate) → Task 1 Steps 3 (`_blended_commission_rate`), 9.
- §7 (gross==0 → rate 0, held excluded, currency-scoped) → `_blended_commission_rate` guard; held-escrow exclusion covered by unchanged `released_escrow_exists` predicate + the existing `escrow_status="held"` seed line in `test_released_attestation_fees_are_withdrawable_earnings`.
- §9 tests 1–6 → Task 1 Steps 1/6, 8, 9, 7 (regression), plus blended math in 9. §9 tests 7–8 → Task 2.
- §10 (no migration/escrow/endpoint change) → honored; only `service.py` + tests touched.

**Placeholder scan:** none — all steps carry full code and exact commands/expected output.

**Type consistency:** `_available_payout_balance` keeps its 5-tuple; callers `get_contributor_earnings` and `request_payout` unpack it unchanged. `_sum_transactions` gains a required `earning_class: str`; both call sites are inside `_available_payout_balance` and pass it. `_blended_commission_rate(cleared_gross, cleared_net)` and `_attestation_commission_rate(db)` names/signatures match between definition and use.

**Note for reviewer (cross-cutting):** `request_payout` (~line 1331) reuses the blended `commission_rate` for the payout gross-up. This is intentional and correct — for single-source earners the blend equals that source's exact rate (0.10 / 0.15); for mixed earners it is the honest effective rate. Solvency is unaffected because claims are netted via `Payout.net_amount` against net `available`, not via the gross-up.
