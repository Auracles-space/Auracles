# Attestation Module 6d — Invoicing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a shared, tax-compliant `invoicing` module (immutable issued-invoice ledger + gapless numbering), issue attestation tax invoices + earnings statements + annual earnings summaries, and retrofit framework purchase invoices onto it.

**Architecture:** New `app/modules/invoicing/` owns an immutable `Invoice` ledger and a gapless number allocator (`invoice_counters` + `SELECT … FOR UPDATE`, atomic with the insert). PDFs render from the frozen row via WeasyPrint and land in the private reports S3 bucket, delivered lazily (302 presigned / 202 enqueue), mirroring the existing purchase-invoice retrieval shape. Attestation-side glue (party RBAC, settled gate, fee-transaction resolution) lives in the attestation module; annual summaries are a derived Beat batch outside the ledger.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, PostgreSQL 16, Celery + Celery Beat, WeasyPrint, loguru, pytest / pytest-asyncio / httpx / freezegun, `uv`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-02-attestation-module-6d-invoicing-design.md`. Every task maps to spec §12 slices.
- Backend-only. No frontend. Update `contracts/openapi.yaml` for every new endpoint (Task 7).
- TDD: write the failing test first, minimal code to green, one behavior at a time. No horizontal slicing.
- Migration head is **`2026_07_02_0055`**; new migration `revision="2026_07_02_0056"`, `down_revision="2026_07_02_0055"`. `alembic upgrade head` **and** `downgrade -1` must both pass.
- Test DB `auracles_test` is provisioned/migrated **externally** (`make test-db`); conftest does NOT migrate. Live-migration tests must self-seed any config they depend on.
- Whole-repo lint/type before claiming a task clean, run from `backend/`: `uv run ruff check .` and `uv run mypy app`. CI lints tests too.
- Commit messages end at the last meaningful line — **no `Co-Authored-By: Claude` trailer**. Work directly on `main`; do not create branches.
- Docstrings: Google-style module/class/function docstrings on all new files and public functions (project standard). Map endpoints to FR-FIN-003/004 in docstrings where relevant.
- Logging via `loguru` with `module=` / `action=` binds; never log presigned URLs or secrets — log `invoice_id` / `attestation_id` / `invoice_number` only.
- Money: `Decimal`, quantize to `Decimal("0.01")`. Gapless numbering is a hard requirement — a rolled-back issue must not burn a number.
- Series constants: `AUR-INV` (sales: purchase + attestation), `AUR-ERN` (earnings statements). Per-year reset. Number format `{series}-{year}-{seq:06d}`.
- No escrow/settlement/payout/balance change. Invoicing is read-only over settled transactions; it writes only the `Invoice` document ledger.

**Settled predicate (used by Tasks 4–6):** an attestation is settled ⇔ `Attestation.status == "closed"` (set together with `report_published_eligible = True` in `attestation/release_service._release_and_close`).

**Attestation fee transaction:** `Transaction` where `transaction_type == "attestation_fee"`, `ref_type == "attestation"`, `ref_id == attestation_id`, `payer_id == requestor`, `amount` = full fee, `currency == "USD"`.

---

### Task 1: `invoicing` module — models, migration, gapless `issue_invoice` service, config

**Files:**
- Create: `backend/app/modules/invoicing/__init__.py`
- Create: `backend/app/modules/invoicing/models.py` (`Invoice`, `InvoiceCounter`)
- Create: `backend/app/modules/invoicing/keys.py` (`invoice_pdf_key`)
- Create: `backend/app/modules/invoicing/service.py` (`SellerIdentity`, `seller_identity`, `issue_invoice`, `get_invoice`, `_tax_rate`, series/doc constants)
- Create: `backend/migrations/versions/2026_07_02_0056_invoicing_ledger.py`
- Modify: `backend/app/core/config.py` — add `invoice_seller_name`, `invoice_seller_tax_id`, `invoice_seller_address` settings.
- Modify: `backend/app/core/database.py` model import registry if models must be imported for Alembic autogen/metadata (follow how existing modules register — check `app/modules/*/models.py` are imported in `app/main.py` or a models aggregator).
- Test: `backend/tests/unit/modules/test_invoicing_service.py`
- Test: `backend/tests/unit/modules/test_invoicing_ledger_migration.py`

**Interfaces:**
- Consumes: `app.shared.models.base.Base` + mixins (`CreatedAtMixin`) — match `financials/models.py` imports; `app.core.config.get_settings`; `financials.PlatformConfig` for the tax-rate config read (import the model, not the private financials helper).
- Produces:
  - Constants: `SERIES_SALES = "AUR-INV"`, `SERIES_EARNINGS = "AUR-ERN"`, `DOC_SALES_INVOICE = "sales_invoice"`, `DOC_EARNINGS_STATEMENT = "earnings_statement"`.
  - `@dataclass(frozen=True) class SellerIdentity: name: str; tax_id: str; address: str`
  - `def seller_identity(settings) -> SellerIdentity`
  - `async def issue_invoice(db, *, doc_type: str, series: str, source_ref_type: str, source_ref_id: UUID, currency: str, subtotal: Decimal, seller: SellerIdentity, buyer_name: str, buyer_email: str, commission_rate: Decimal | None = None, net_amount: Decimal | None = None) -> Invoice`
  - `async def get_invoice(db, *, source_ref_type: str, source_ref_id: UUID, doc_type: str) -> Invoice | None`
  - `def invoice_pdf_key(doc_type: str, invoice_id: UUID) -> str` → `f"invoices/{doc_type}/{invoice_id}.pdf"`
  - `Invoice` columns per spec §4.1; `InvoiceCounter(series, year, last_number)`.

**`Invoice` model (spec §4.1) — columns:** `id` (UUID PK, `gen_random_uuid()`), `series` (str), `sequence_year` (int), `sequence_number` (int), `invoice_number` (str, unique), `doc_type` (str), `issue_date` (timestamptz, `now()`), `currency` (char3), `subtotal` (Numeric(12,2)), `tax_rate` (Numeric(5,4)), `tax_amount` (Numeric(12,2)), `total` (Numeric(12,2)), `commission_rate` (Numeric(5,4), nullable), `net_amount` (Numeric(12,2), nullable), `seller_name`/`seller_tax_id`/`seller_address` (str), `buyer_name`/`buyer_email` (str), `source_ref_type` (str), `source_ref_id` (UUID), `s3_key` (str), `created_at`.
Constraints: `UniqueConstraint("series","sequence_year","sequence_number", name="uq_invoices_series_seq")`, `UniqueConstraint("invoice_number", name="uq_invoices_number")`, `UniqueConstraint("source_ref_type","source_ref_id","doc_type", name="uq_invoices_source_doc")`, `CheckConstraint("subtotal >= 0")`, `CheckConstraint("total >= 0")`, `CheckConstraint("tax_rate >= 0")`, `Index("idx_invoices_source","source_ref_type","source_ref_id")`.
**`InvoiceCounter`:** `__tablename__ = "invoice_counters"`, PK composite `(series, year)`, `last_number` int not null default 0.

- [ ] **Step 1: Write the failing test — first issue allocates AUR-INV-2026-000001**

Create `backend/tests/unit/modules/test_invoicing_service.py`. Use the existing async-session fixture style from `tests/unit/workers/test_reputation_tasks.py` (`async_session_factory`, dispose engine, clean `Invoice`/`InvoiceCounter` before/after). Freeze time to 2026.

```python
"""Unit tests for the invoicing ledger + gapless allocator (Module 6d)."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from freezegun import freeze_time
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.modules.invoicing import service as invoicing
from app.modules.invoicing.models import Invoice, InvoiceCounter


@pytest.fixture
async def clean_invoicing():
    await engine.dispose()
    async def _clean():
        async with async_session_factory() as s:
            await s.execute(delete(Invoice))
            await s.execute(delete(InvoiceCounter))
            await s.commit()
    await _clean()
    yield
    await _clean()
    await engine.dispose()


def _seller():
    return invoicing.seller_identity(get_settings())


@pytest.mark.asyncio
@freeze_time("2026-05-01")
async def test_first_issue_allocates_number_one(clean_invoicing):
    """First issued sales invoice in 2026 is AUR-INV-2026-000001."""
    src = uuid4()
    async with async_session_factory() as db:
        inv = await invoicing.issue_invoice(
            db,
            doc_type=invoicing.DOC_SALES_INVOICE,
            series=invoicing.SERIES_SALES,
            source_ref_type="transaction",
            source_ref_id=src,
            currency="USD",
            subtotal=Decimal("500.00"),
            seller=_seller(),
            buyer_name="Ada Op",
            buyer_email="ada@example.com",
        )
        await db.commit()
    assert inv.sequence_number == 1
    assert inv.invoice_number == "AUR-INV-2026-000001"
    assert inv.total == Decimal("500.00")  # tax rate defaults to 0
    assert inv.s3_key == f"invoices/sales_invoice/{inv.id}.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && DATABASE_URL="postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test" uv run pytest tests/unit/modules/test_invoicing_service.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.invoicing` (and the `invoices`/`invoice_counters` tables don't exist yet).

- [ ] **Step 3: Create the models**

`backend/app/modules/invoicing/models.py` — model the columns/constraints above, following the exact import + column style of `backend/app/modules/financials/models.py` (`Mapped`, `mapped_column`, `PG_UUID(as_uuid=True)`, `Numeric`, `text("gen_random_uuid()")`, `CreatedAtMixin`, `Base`). Module docstring: "Invoicing ledger models — immutable issued-invoice register + gapless counter (FR-FIN-003)."

`backend/app/modules/invoicing/keys.py`:
```python
"""Deterministic S3 keys for issued invoice documents."""
from __future__ import annotations
from uuid import UUID

def invoice_pdf_key(doc_type: str, invoice_id: UUID) -> str:
    """Return the private S3 key for an issued invoice PDF."""
    return f"invoices/{doc_type}/{invoice_id}.pdf"
```

- [ ] **Step 4: Create the migration**

`backend/migrations/versions/2026_07_02_0056_invoicing_ledger.py`, `revision="2026_07_02_0056"`, `down_revision="2026_07_02_0055"`. Follow the structure of `backend/migrations/versions/2026_07_02_0055_attestation_badges_provenance.py`: `upgrade()` `op.create_table("invoice_counters", ...)` and `op.create_table("invoices", ...)` with all columns + the four constraints + index; `downgrade()` drops `invoices` then `invoice_counters`. Docstring explains the WHY (gapless issued-invoice ledger, FR-FIN-003).

- [ ] **Step 5: Apply the migration to the test DB**

Run: `cd backend && DATABASE_URL="postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test" uv run alembic upgrade head`
Expected: revision `2026_07_02_0056` applied; `invoices` + `invoice_counters` created.

- [ ] **Step 6: Add config + implement `service.py`**

Add to `backend/app/core/config.py` (near `s3_reports_bucket`):
```python
invoice_seller_name: str = Field(default="Auracles (pending registration)", alias="INVOICE_SELLER_NAME")
invoice_seller_tax_id: str = Field(default="", alias="INVOICE_SELLER_TAX_ID")
invoice_seller_address: str = Field(default="", alias="INVOICE_SELLER_ADDRESS")
```

`backend/app/modules/invoicing/service.py` — implement. Core allocator (gapless, idempotent):
```python
"""Invoicing service — gapless invoice issuance over an immutable ledger.

Issues sales invoices (AUR-INV) and earnings statements (AUR-ERN). Numbers are
gapless per (series, year) via a counter row locked FOR UPDATE inside the same
transaction as the Invoice insert, so a rollback never burns a number.
Maps to: FR-FIN-003.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.financials.models import PlatformConfig
from app.modules.invoicing.keys import invoice_pdf_key
from app.modules.invoicing.models import Invoice, InvoiceCounter

SERIES_SALES = "AUR-INV"
SERIES_EARNINGS = "AUR-ERN"
DOC_SALES_INVOICE = "sales_invoice"
DOC_EARNINGS_STATEMENT = "earnings_statement"
_CENTS = Decimal("0.01")
_RATE = Decimal("0.0001")


@dataclass(frozen=True)
class SellerIdentity:
    """Snapshot of the issuing entity identity, sourced from config."""
    name: str
    tax_id: str
    address: str


def seller_identity(settings) -> SellerIdentity:
    """Build the seller identity from settings (real values injected via env)."""
    return SellerIdentity(
        name=settings.invoice_seller_name,
        tax_id=settings.invoice_seller_tax_id,
        address=settings.invoice_seller_address,
    )


async def _tax_rate(db: AsyncSession) -> Decimal:
    """Return the configured invoice tax rate (platform_config, default 0)."""
    value = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == "invoice_tax_rate")
    )
    return Decimal(value) if value is not None else Decimal("0")


async def get_invoice(
    db: AsyncSession, *, source_ref_type: str, source_ref_id: UUID, doc_type: str
) -> Invoice | None:
    """Return the already-issued invoice for a source + doc type, if any."""
    return await db.scalar(
        select(Invoice).where(
            Invoice.source_ref_type == source_ref_type,
            Invoice.source_ref_id == source_ref_id,
            Invoice.doc_type == doc_type,
        )
    )


async def issue_invoice(
    db: AsyncSession,
    *,
    doc_type: str,
    series: str,
    source_ref_type: str,
    source_ref_id: UUID,
    currency: str,
    subtotal: Decimal,
    seller: SellerIdentity,
    buyer_name: str,
    buyer_email: str,
    commission_rate: Decimal | None = None,
    net_amount: Decimal | None = None,
) -> Invoice:
    """Idempotently issue one immutable invoice with a gapless number.

    Returns the existing invoice if one was already issued for this
    (source_ref_type, source_ref_id, doc_type). Otherwise locks the
    (series, year) counter, allocates the next number, and inserts the frozen
    Invoice row in the same transaction.

    The caller owns the transaction boundary (does not commit here).
    """
    existing = await get_invoice(
        db, source_ref_type=source_ref_type, source_ref_id=source_ref_id, doc_type=doc_type
    )
    if existing is not None:
        return existing

    tax_rate = await _tax_rate(db)
    subtotal = subtotal.quantize(_CENTS)
    tax_amount = (subtotal * tax_rate).quantize(_CENTS)
    total = (subtotal + tax_amount).quantize(_CENTS)

    now_year = (await db.scalar(select(func.extract("year", func.now()))))  # int
    year = int(now_year)

    # Ensure the counter row exists, then lock it.
    await db.execute(
        pg_insert(InvoiceCounter)
        .values(series=series, year=year, last_number=0)
        .on_conflict_do_nothing(index_elements=["series", "year"])
    )
    counter = await db.scalar(
        select(InvoiceCounter)
        .where(InvoiceCounter.series == series, InvoiceCounter.year == year)
        .with_for_update()
    )
    counter.last_number += 1
    seq = counter.last_number
    invoice_number = f"{series}-{year}-{seq:06d}"

    invoice = Invoice(
        series=series,
        sequence_year=year,
        sequence_number=seq,
        invoice_number=invoice_number,
        doc_type=doc_type,
        currency=currency,
        subtotal=subtotal,
        tax_rate=tax_rate.quantize(_RATE),
        tax_amount=tax_amount,
        total=total,
        commission_rate=(commission_rate.quantize(_RATE) if commission_rate is not None else None),
        net_amount=(net_amount.quantize(_CENTS) if net_amount is not None else None),
        seller_name=seller.name,
        seller_tax_id=seller.tax_id,
        seller_address=seller.address,
        buyer_name=buyer_name,
        buyer_email=buyer_email,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
    )
    db.add(invoice)
    await db.flush()
    invoice.s3_key = invoice_pdf_key(doc_type, invoice.id)
    await db.flush()
    return invoice
```
Add `from sqlalchemy import func` to imports. (The `func.extract("year", func.now())` keeps the year in DB time, consistent with `now()` defaults.)

- [ ] **Step 7: Run the first test to green**

Run: `cd backend && DATABASE_URL="postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test" uv run pytest tests/unit/modules/test_invoicing_service.py -v`
Expected: PASS.

- [ ] **Step 8: Add the gapless + idempotency + reset + tax + earnings behaviors (one test each, RED→GREEN)**

Add these tests to the same file; each should pass against the Step 6 implementation (they exercise behavior, not new code — if one fails, fix the implementation):

```python
@pytest.mark.asyncio
@freeze_time("2026-05-01")
async def test_second_issue_is_gapless_consecutive(clean_invoicing):
    """Two issues in the same series/year get consecutive numbers."""
    async with async_session_factory() as db:
        a = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="transaction", source_ref_id=uuid4(), currency="USD", subtotal=Decimal("100.00"), seller=_seller(), buyer_name="A", buyer_email="a@x.com")
        b = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="transaction", source_ref_id=uuid4(), currency="USD", subtotal=Decimal("100.00"), seller=_seller(), buyer_name="B", buyer_email="b@x.com")
        await db.commit()
    assert (a.sequence_number, b.sequence_number) == (1, 2)


@pytest.mark.asyncio
@freeze_time("2026-05-01")
async def test_issue_is_idempotent_per_source_doc(clean_invoicing):
    """Re-issuing the same source+doc returns the same row, no new number."""
    src = uuid4()
    async with async_session_factory() as db:
        a = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="attestation", source_ref_id=src, currency="USD", subtotal=Decimal("500.00"), seller=_seller(), buyer_name="A", buyer_email="a@x.com")
        await db.commit()
    async with async_session_factory() as db:
        b = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="attestation", source_ref_id=src, currency="USD", subtotal=Decimal("500.00"), seller=_seller(), buyer_name="A", buyer_email="a@x.com")
        await db.commit()
    assert a.id == b.id and a.invoice_number == b.invoice_number


@pytest.mark.asyncio
async def test_rollback_does_not_burn_a_number(clean_invoicing):
    """A rolled-back issue leaves the next number un-consumed (gapless)."""
    with freeze_time("2026-05-01"):
        async with async_session_factory() as db:
            await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="transaction", source_ref_id=uuid4(), currency="USD", subtotal=Decimal("100.00"), seller=_seller(), buyer_name="A", buyer_email="a@x.com")
            await db.rollback()  # discard
        async with async_session_factory() as db:
            kept = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="transaction", source_ref_id=uuid4(), currency="USD", subtotal=Decimal("100.00"), seller=_seller(), buyer_name="A", buyer_email="a@x.com")
            await db.commit()
    assert kept.sequence_number == 1  # rolled-back attempt did not advance the counter


@pytest.mark.asyncio
async def test_number_resets_per_year(clean_invoicing):
    """A new calendar year restarts the sequence at 1."""
    with freeze_time("2026-12-31"):
        async with async_session_factory() as db:
            y26 = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="transaction", source_ref_id=uuid4(), currency="USD", subtotal=Decimal("1.00"), seller=_seller(), buyer_name="A", buyer_email="a@x.com")
            await db.commit()
    with freeze_time("2027-01-02"):
        async with async_session_factory() as db:
            y27 = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="transaction", source_ref_id=uuid4(), currency="USD", subtotal=Decimal("1.00"), seller=_seller(), buyer_name="A", buyer_email="a@x.com")
            await db.commit()
    assert y26.invoice_number.endswith("2026-000001")
    assert y27.invoice_number.endswith("2027-000001")


@pytest.mark.asyncio
@freeze_time("2026-05-01")
async def test_earnings_statement_snapshots_rate_and_net(clean_invoicing):
    """Earnings statement stores commission rate + net = subtotal*(1-rate)."""
    async with async_session_factory() as db:
        inv = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_EARNINGS_STATEMENT, series=invoicing.SERIES_EARNINGS, source_ref_type="attestation", source_ref_id=uuid4(), currency="USD", subtotal=Decimal("500.00"), seller=_seller(), buyer_name="Att Estor", buyer_email="att@x.com", commission_rate=Decimal("0.10"), net_amount=Decimal("450.00"))
        await db.commit()
    assert inv.series == "AUR-ERN"
    assert inv.commission_rate == Decimal("0.1000")
    assert inv.net_amount == Decimal("450.00")
```

Note: the year-reset test writes a 2026 row then a 2027 row without cleaning between — both persist, distinct `(series, year)` counters. `clean_invoicing` wipes at test end.

- [ ] **Step 9: Add the tax-rate override test (seeds config)**

```python
from app.modules.financials.models import PlatformConfig

@pytest.mark.asyncio
@freeze_time("2026-05-01")
async def test_tax_rate_from_config_applies(clean_invoicing):
    """A configured invoice_tax_rate produces a tax line and total."""
    async with async_session_factory() as db:
        db.add(PlatformConfig(key="invoice_tax_rate", value="0.075"))
        await db.commit()
    try:
        async with async_session_factory() as db:
            inv = await invoicing.issue_invoice(db, doc_type=invoicing.DOC_SALES_INVOICE, series=invoicing.SERIES_SALES, source_ref_type="transaction", source_ref_id=uuid4(), currency="USD", subtotal=Decimal("200.00"), seller=_seller(), buyer_name="A", buyer_email="a@x.com")
            await db.commit()
        assert inv.tax_amount == Decimal("15.00")
        assert inv.total == Decimal("215.00")
    finally:
        async with async_session_factory() as db:
            await db.execute(delete(PlatformConfig).where(PlatformConfig.key == "invoice_tax_rate"))
            await db.commit()
```

Run after each: `cd backend && DATABASE_URL="postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test" uv run pytest tests/unit/modules/test_invoicing_service.py -v` → all PASS.

- [ ] **Step 10: Migration up/down test**

`backend/tests/unit/modules/test_invoicing_ledger_migration.py` — copy the shape of `backend/tests/unit/modules/test_attestation_badges_migration.py` with `PREVIOUS_HEAD = "2026_07_02_0055"`. Assert after upgrade: `invoices` and `invoice_counters` in `inspector.get_table_names()`, `uq_invoices_series_seq` / `uq_invoices_source_doc` in unique constraints. Assert downgrade -1 removes both tables. Restore to head in `finally`.

- [ ] **Step 11: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/invoicing backend/migrations/versions/2026_07_02_0056_invoicing_ledger.py backend/app/core/config.py backend/tests/unit/modules/test_invoicing_service.py backend/tests/unit/modules/test_invoicing_ledger_migration.py
git commit -m "Add invoicing ledger + gapless issue_invoice service (6d)"
```

---

### Task 2: Shared invoice render (sales invoice + earnings statement templates)

**Files:**
- Create: `backend/app/modules/invoicing/render.py` (`render_invoice_pdf`, two Jinja templates)
- Test: `backend/tests/unit/modules/test_invoicing_render.py`

**Interfaces:**
- Consumes: `Invoice` (Task 1), `weasyprint.HTML`, `jinja2.Environment`.
- Produces: `def render_invoice_pdf(invoice: Invoice, *, line_item_label: str) -> bytes` — selects the template by `invoice.doc_type`, renders from the frozen row only, returns PDF bytes.

- [ ] **Step 1: Failing test — both doc types render non-empty PDF from a frozen row**

```python
"""Unit tests for invoice PDF rendering from the frozen ledger row (6d)."""
from __future__ import annotations
from decimal import Decimal
from uuid import uuid4

from app.modules.invoicing import service as invoicing
from app.modules.invoicing.models import Invoice
from app.modules.invoicing.render import render_invoice_pdf


def _sales_invoice() -> Invoice:
    return Invoice(
        id=uuid4(), series="AUR-INV", sequence_year=2026, sequence_number=1,
        invoice_number="AUR-INV-2026-000001", doc_type="sales_invoice",
        currency="USD", subtotal=Decimal("500.00"), tax_rate=Decimal("0.0000"),
        tax_amount=Decimal("0.00"), total=Decimal("500.00"),
        commission_rate=None, net_amount=None,
        seller_name="Auracles Ltd", seller_tax_id="TAX-1", seller_address="1 St",
        buyer_name="Ada Op", buyer_email="ada@example.com",
        source_ref_type="attestation", source_ref_id=uuid4(),
        s3_key="invoices/sales_invoice/x.pdf",
    )


def test_sales_invoice_renders_pdf_with_number_and_seller():
    """Sales invoice PDF renders and embeds number, seller, total."""
    pdf = render_invoice_pdf(_sales_invoice(), line_item_label="Expert Attestation")
    assert pdf[:4] == b"%PDF"


def test_earnings_statement_renders_net():
    """Earnings statement PDF renders from an AUR-ERN row."""
    row = _sales_invoice()
    row.series = "AUR-ERN"; row.doc_type = "earnings_statement"
    row.commission_rate = Decimal("0.1000"); row.net_amount = Decimal("450.00")
    row.invoice_number = "AUR-ERN-2026-000001"
    pdf = render_invoice_pdf(row, line_item_label="Expert Attestation")
    assert pdf[:4] == b"%PDF"
```

- [ ] **Step 2: Run — FAIL** (`render` module missing).
Run: `cd backend && uv run pytest tests/unit/modules/test_invoicing_render.py -v`

- [ ] **Step 3: Implement `render.py`**

Two `jinja2.Environment(autoescape=True).from_string(...)` templates (follow `workers/tasks/attestation_pdf.py:REPORT_TEMPLATE` style — inline CSS, no external fonts to avoid network in render). Sales-invoice template shows: seller block (name/tax id/address), buyer block, `invoice_number`, `issue_date`, one line item (`line_item_label` + `subtotal`), `Tax ({{ tax_rate*100 }}%): {{ tax_amount }}`, `Total: {{ total }} {{ currency }}`. Earnings-statement template shows: attestor (buyer_*), `invoice_number`, gross (`subtotal`), `Platform commission ({{ commission_rate*100 }}%)`, `Net earnings: {{ net_amount }}`. `render_invoice_pdf` picks template by `invoice.doc_type`, builds a context dict of formatted strings (quantize money to `0.01`), returns `HTML(string=html).write_pdf()`. Do **not** hit the DB or recompute — read only fields off `invoice`.

- [ ] **Step 4: Run — PASS.** Same command.

- [ ] **Step 5: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/invoicing/render.py backend/tests/unit/modules/test_invoicing_render.py
git commit -m "Add shared invoice + earnings-statement PDF render (6d)"
```

---

### Task 3: Retrofit framework purchase invoice onto `invoicing`

**Files:**
- Modify: `backend/app/workers/tasks/financials.py` — replace `_render_purchase_invoice_pdf` internals to render from an issued `Invoice`; keep `generate_invoice_pdf` task name/signature.
- Modify: `backend/app/modules/financials/service.py:579-620` `get_framework_purchase_invoice` — issue the invoice, use the new `invoice.s3_key`, enqueue `generate_invoice_pdf`.
- Test: `backend/tests/integration/test_financials_purchase_invoice.py` (existing — extend/adjust; if absent, add) and a focused `backend/tests/unit/workers/test_purchase_invoice_retrofit.py`.

**Interfaces:**
- Consumes: `invoicing.issue_invoice`, `invoicing.get_invoice`, `invoicing.seller_identity`, `invoicing.SERIES_SALES`, `invoicing.DOC_SALES_INVOICE`, `invoicing.render.render_invoice_pdf`.
- Produces: purchase invoice now stored at `invoices/sales_invoice/{invoice_id}.pdf`; endpoint contract unchanged (409 unsettled, 302 presigned, 202 enqueue).

- [ ] **Step 1: Find the current purchase-invoice tests**

Run: `cd backend && grep -rln "purchase.*invoice\|get_framework_purchase_invoice\|generate_invoice_pdf" tests/`
Read them. The retrofit must keep their endpoint-contract assertions green (409/302/202, auth). Only the storage key + PDF internals change.

- [ ] **Step 2: Failing test — a settled purchase issues a compliant numbered invoice**

Add `backend/tests/integration/test_financials_purchase_invoice.py::test_purchase_invoice_is_issued_and_numbered` (or extend the existing file). Using the existing purchase/transaction factories, create a `completed` framework purchase, call `GET /v1/financials/purchases/{txn_id}/invoice`; first call → 202; assert an `Invoice` row now exists with `series="AUR-INV"`, `doc_type="sales_invoice"`, `source_ref_type="transaction"`, `source_ref_id=txn_id`, `invoice_number` matching `^AUR-INV-\d{4}-\d{6}$`. (Model the request/fixtures on the existing purchase-invoice test found in Step 1.)

- [ ] **Step 3: Run — FAIL** (no `Invoice` issued yet).

- [ ] **Step 4: Implement the retrofit**

In `financials/service.get_framework_purchase_invoice`: after the `status in {"completed","refunded"}` gate, load the operator (`User`) + framework title, then:
```python
from app.modules.invoicing import service as invoicing
inv = await invoicing.issue_invoice(
    db,
    doc_type=invoicing.DOC_SALES_INVOICE,
    series=invoicing.SERIES_SALES,
    source_ref_type="transaction",
    source_ref_id=transaction_id,
    currency=transaction.currency,
    subtotal=transaction.amount,
    seller=invoicing.seller_identity(get_settings()),
    buyer_name=operator.display_name,
    buyer_email=operator.email,
)
await db.commit()
key = inv.s3_key
```
Replace `purchase_invoice_key(transaction_id)` usage with `inv.s3_key`. Keep the `object_exists → 302 presigned / else .delay(...) + 202` shape. In `workers/tasks/financials.py`, change `_render_purchase_invoice_pdf` to: load the issued `Invoice` (`invoicing.get_invoice(..., source_ref_type="transaction", source_ref_id=UUID(transaction_id), doc_type=DOC_SALES_INVOICE)`) + the framework title, call `render_invoice_pdf(invoice, line_item_label=framework.title)`, return `invoice.s3_key, pdf_bytes`. Retire the old `INVOICE_TEMPLATE`/`purchase_invoice_key` path (leave `purchase_invoice_key` in `invoices.py` only if still referenced; otherwise delete it and its import). Legacy S3 objects under `invoices/purchases/` are left untouched (forward-only).

- [ ] **Step 5: Run the new test + the existing purchase-invoice tests — all PASS**

Run: `cd backend && DATABASE_URL="postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test" uv run pytest tests/integration/test_financials_purchase_invoice.py tests/unit/workers/test_purchase_invoice_retrofit.py -v` (adjust paths to the files found in Step 1).
Expected: PASS — regression guard intact.

- [ ] **Step 6: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/workers/tasks/financials.py backend/app/modules/financials/service.py backend/app/modules/financials/invoices.py backend/tests
git commit -m "Retrofit framework purchase invoice onto shared invoicing ledger (6d)"
```

---

### Task 4: Attestation tax-invoice endpoint

**Files:**
- Create: `backend/app/modules/attestation/document_service.py` (`get_tax_invoice`, shared helpers `_load_settled_attestation`, `_is_admin`, `_attestation_fee_transaction`, `_deliver_invoice`)
- Create: `backend/app/workers/tasks/invoicing.py` (`generate_invoice_document` Celery task)
- Modify: `backend/app/modules/attestation/router.py` — add `GET /attestations/{attestation_id}/invoice`
- Test: `backend/tests/integration/test_attestation_invoice_endpoints.py`

**Interfaces:**
- Consumes: `invoicing.issue_invoice/get_invoice/seller_identity`, `invoicing.render.render_invoice_pdf`, `s3.storage`, `Attestation`, `Transaction`, `require_role`, approved-admin `UserRole` query (pattern from `frameworks/router.py:192-202`).
- Produces:
  - `async def get_tax_invoice(db, *, attestation_id: UUID, user: User) -> Response` (302/202)
  - Celery task `generate_invoice_document(invoice_id: str) -> dict[str,str]` — loads the `Invoice`, resolves its human line-item label from the source, renders, uploads to `s3_reports_bucket` at `invoice.s3_key`.
  - `def _review_type_label(attestation: Attestation) -> str` for the line item.

**Line-item label:** for attestation docs use the attestation `review_type` humanized (e.g. `"Expert Attestation"`); the render task resolves it from `source_ref_id` when `source_ref_type == "attestation"`.

- [ ] **Step 1: Failing tests — requestor 202→302, unsettled 409, cross-party 403**

`backend/tests/integration/test_attestation_invoice_endpoints.py`. Build a **closed** attestation with a funded `attestation_fee` transaction using existing attestation factories/fixtures (grep `tests/` for how other attestation integration tests set `status="closed"` and create the fee `Transaction`). Tests:
```python
async def test_requestor_gets_tax_invoice(client, ...):
    """Requestor GET on a settled attestation → 202 then 302 to a presigned PDF."""
    # first call enqueues
    r1 = await client.get(f"/v1/attestations/{att_id}/invoice", headers=requestor_auth)
    assert r1.status_code == 202
    # run the render task synchronously, then second call redirects
    from app.workers.tasks.invoicing import generate_invoice_document
    inv_id = ...  # fetch issued Invoice id
    generate_invoice_document.apply(args=[str(inv_id)])
    r2 = await client.get(f"/v1/attestations/{att_id}/invoice", headers=requestor_auth)
    assert r2.status_code == 302

async def test_unsettled_attestation_invoice_409(client, ...):
    """A not-yet-closed attestation → 409."""
    assert (await client.get(f"/v1/attestations/{open_att_id}/invoice", headers=requestor_auth)).status_code == 409

async def test_attestor_cannot_fetch_tax_invoice(client, ...):
    """The attestor is not a party to the buyer tax invoice → 403."""
    assert (await client.get(f"/v1/attestations/{att_id}/invoice", headers=attestor_auth)).status_code == 403
```

- [ ] **Step 2: Run — FAIL** (route missing).

- [ ] **Step 3: Implement `document_service.get_tax_invoice` + task + route**

`document_service.py`:
```python
"""Attestation invoice-document delivery (tax invoice + earnings statement).

Resolves the settled attestation + its fee transaction, issues the invoice via
the shared invoicing ledger, and delivers the PDF lazily (302 presigned / 202
enqueue). RBAC (party membership + admin) is enforced by the router dependency;
this layer re-checks party identity for defence in depth. FR-FIN-003/004.
"""
```
`_load_settled_attestation(db, attestation_id)` → `Attestation` or `HTTPException(404)`; if `status != "closed"` → `HTTPException(409, "Invoice is only available for settled attestations.")`. `_attestation_fee_transaction(db, attestation_id)` → the `attestation_fee` `Transaction` (404 if missing). `get_tax_invoice`: check `user.id == attestation.requestor_id or _is_admin(db, user)` else 403 (+ WARNING log `access_denied`); resolve fee txn; `inv = await issue_invoice(db, doc_type=DOC_SALES_INVOICE, series=SERIES_SALES, source_ref_type="attestation", source_ref_id=attestation_id, currency=txn.currency, subtotal=txn.amount, seller=seller_identity(settings), buyer_name=requestor.display_name, buyer_email=requestor.email)`; `await db.commit()`; then `_deliver_invoice(inv)` → 302 presigned if `s3.storage.object_exists(bucket, inv.s3_key)` else `generate_invoice_document.delay(str(inv.id))` + 202 (reuse `INVOICE_URL_TTL_SECONDS`, `InvoiceGenerationResponse` shape from financials; add an attestation-scoped response schema if the existing one is transaction-keyed). Audit-log admin cross-party fetches via `write_audit`.

`workers/tasks/invoicing.py`: `generate_invoice_document(invoice_id)` loads the `Invoice`; if `source_ref_type == "attestation"`, load the `Attestation` → `line_item_label = _review_type_label(att)`; if `"transaction"`, load framework title; `pdf = render_invoice_pdf(invoice, line_item_label=label)`; `s3.storage.upload_bytes(settings.s3_reports_bucket, invoice.s3_key, pdf, "application/pdf")`. `bind=True, max_retries=3`, retry `countdown=60`, loguru binds `module="invoicing"`, `action="generate_invoice_document"`, `invoice_id`.

Route in `attestation/router.py` (thin):
```python
@router.get("/attestations/{attestation_id}/invoice")
async def get_attestation_invoice(
    attestation_id: UUID,
    db: DatabaseSession,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Deliver the Requestor tax invoice for a settled attestation (FR-FIN-003)."""
    return await document_service.get_tax_invoice(db, attestation_id=attestation_id, user=user)
```

- [ ] **Step 4: Run — PASS.**
Run: `cd backend && DATABASE_URL="postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test" uv run pytest tests/integration/test_attestation_invoice_endpoints.py -v`

- [ ] **Step 5: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/document_service.py backend/app/workers/tasks/invoicing.py backend/app/modules/attestation/router.py backend/tests/integration/test_attestation_invoice_endpoints.py
git commit -m "Add attestation tax-invoice endpoint (6d)"
```

---

### Task 5: Attestation earnings-statement endpoint

**Files:**
- Modify: `backend/app/modules/attestation/document_service.py` — add `get_earnings_statement`
- Modify: `backend/app/modules/attestation/router.py` — add `GET /attestations/{attestation_id}/earnings-statement`
- Modify: `backend/tests/integration/test_attestation_invoice_endpoints.py` — add earnings-statement cases

**Interfaces:**
- Consumes: `issue_invoice(doc_type=DOC_EARNINGS_STATEMENT, series=SERIES_EARNINGS, ...)`, the attestation commission rate. To avoid depending on financials' private helper, read the rate inline: `select(PlatformConfig.value).where(PlatformConfig.key == "attestation_commission_rate")` default `Decimal("0.10")`.
- Produces: `async def get_earnings_statement(db, *, attestation_id: UUID, user: User) -> Response`.

- [ ] **Step 1: Failing tests — attestor 202→302, requestor 403, net = 90%**

Add to `test_attestation_invoice_endpoints.py`:
```python
async def test_attestor_gets_earnings_statement(client, ...):
    """Attestor GET → 202 then 302; issued AUR-ERN with net = fee*0.90."""
    r1 = await client.get(f"/v1/attestations/{att_id}/earnings-statement", headers=attestor_auth)
    assert r1.status_code == 202
    # assert issued Invoice: series AUR-ERN, net_amount == fee * Decimal("0.90")

async def test_requestor_cannot_fetch_earnings_statement(client, ...):
    """Requestor is not a party to the attestor remittance → 403."""
    assert (await client.get(f"/v1/attestations/{att_id}/earnings-statement", headers=requestor_auth)).status_code == 403
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement `get_earnings_statement` + route**

Mirror `get_tax_invoice` but: party check `user.id == attestation.attestor_id or _is_admin(...)` else 403; `rate = await _attestation_commission_rate(db)`; `net = (fee * (Decimal("1") - rate)).quantize(Decimal("0.01"))`; `issue_invoice(doc_type=DOC_EARNINGS_STATEMENT, series=SERIES_EARNINGS, source_ref_type="attestation", source_ref_id=attestation_id, currency=txn.currency, subtotal=txn.amount, seller=seller_identity(settings), buyer_name=attestor.display_name, buyer_email=attestor.email, commission_rate=rate, net_amount=net)`; deliver via `_deliver_invoice`. Add the thin route (docstring FR-FIN-004).

- [ ] **Step 4: Run — PASS.** Same command as Task 4 Step 4.

- [ ] **Step 5: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/attestation/document_service.py backend/app/modules/attestation/router.py backend/tests/integration/test_attestation_invoice_endpoints.py
git commit -m "Add attestation earnings-statement endpoint (6d)"
```

---

### Task 6: Annual earnings summary — Beat task, render, email, fetch endpoint

**Files:**
- Create: `backend/app/workers/tasks/invoicing_beat.py` (`generate_annual_earnings_summaries`)
- Create: `backend/app/modules/invoicing/annual.py` (`annual_summary_key`, `render_annual_summary_pdf`, `annual_earner_ids`, `annual_line_items`)
- Modify: `backend/app/workers/beat_schedule.py` — add the Jan-2 entry
- Modify: `backend/app/modules/attestation/document_service.py` — add `get_annual_summary`
- Modify: `backend/app/modules/attestation/router.py` — add `GET /attestations/earnings/annual/{year}`
- Test: `backend/tests/unit/workers/test_annual_earnings_summary.py`, extend `test_attestation_invoice_endpoints.py`

**Interfaces:**
- Produces:
  - `def annual_summary_key(attestor_id: UUID, year: int) -> str` → `f"annual-summaries/{attestor_id}/{year}.pdf"`
  - `async def _annual_earner_ids(year: int) -> list[UUID]` (opens its own session) — attestor ids with ≥1 settled `attestation_fee` (attestation `status="closed"`) whose settlement falls in `year`. A thin `async def annual_earner_ids(db, year: int) -> list[UUID]` variant taking a session backs the unit tests.
  - `async def annual_line_items(db, *, attestor_id: UUID, year: int) -> tuple[list[dict], dict]` — line items + totals.
  - `def render_annual_summary_pdf(*, attestor_name, year, line_items, totals) -> bytes`
  - Celery `generate_annual_earnings_summaries()` (no args; computes prior year) + `generate_annual_earnings_summary(attestor_id: str, year: int)` (per-attestor, testable).
  - `async def get_annual_summary(db, *, user: User, year: int) -> Response` — 302 if key exists else 404.

**Year attribution:** attribute an attestation's earnings to the year of its settlement. Use the fee `Transaction.updated_at` on the `closed` attestation, or `Attestation.updated_at` at close — pick the one that reflects close time; document the choice in the task docstring. Filter `year_start <= settled_at < year_start+1y` (UTC).

- [ ] **Step 1: Failing test — per-attestor summary renders + uploads at deterministic key**

`backend/tests/unit/workers/test_annual_earnings_summary.py`, freezegun `2027-01-02`. Seed two attestors with settled 2026 `attestation_fee` transactions + closed attestations, one attestor with none. Monkeypatch `s3.storage.upload_bytes` to capture `(bucket, key, bytes)`. Run `generate_annual_earnings_summaries.apply()`.
```python
async def test_generates_summary_per_earner_not_for_zero(...):
    """Beat run renders one PDF per prior-year earner at annual-summaries/{id}/{year}.pdf."""
    generate_annual_earnings_summaries.apply()
    keys = {k for (_b, k, _p) in captured}
    assert f"annual-summaries/{earner_a}/2026.pdf" in keys
    assert f"annual-summaries/{earner_b}/2026.pdf" in keys
    assert not any(str(zero_earner) in k for k in keys)
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement `annual.py` + the Beat tasks**

`annual.py`: `annual_earner_ids` selects distinct `Attestation.attestor_id` joined to the `attestation_fee` `Transaction`, `Attestation.status == "closed"`, settled-at within `[year, year+1)`. `annual_line_items` returns per-attestation rows (settled date, attestation id, review type, gross `amount`, effective rate from `attestation_commission_rate`, net) + totals (gross, net, count), USD. `render_annual_summary_pdf` — Jinja+WeasyPrint table (style like `attestation_pdf.py`). `invoicing_beat.py`:
```python
@app.task(bind=True, max_retries=3)
def generate_annual_earnings_summaries(self):
    """Render + store prior-year earnings summaries for every earner (Jan-2 Beat)."""
    year = datetime.now(UTC).year - 1
    for attestor_id in run_async(_annual_earner_ids(year)):
        generate_annual_earnings_summary.delay(str(attestor_id), year)
```
`generate_annual_earnings_summary(attestor_id, year)`: build line items, render, `upload_bytes(s3_reports_bucket, annual_summary_key(id, year), pdf, "application/pdf")` (overwrite = idempotent), then enqueue the notification (Step 5). loguru binds `module="invoicing"`, `action="generate_annual_earnings_summary"`, `attestor_id`, `task_id`.

- [ ] **Step 4: Run — PASS.**
Run: `cd backend && DATABASE_URL="postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test" uv run pytest tests/unit/workers/test_annual_earnings_summary.py -v`

- [ ] **Step 5: Add idempotency + notification test, then wire the email**

Test: run the per-attestor task twice → same key overwritten, and the notification dispatch fires with a stable dedupe key (monkeypatch `dispatch_project_notification.delay` / the notification helper, assert called once per `(attestor, year)` dedupe). Implement: after upload, dispatch a durable notification (`dispatch_project_notification.delay(user_id=attestor_id, notification_type="attestation_annual_summary_ready", title="Your {year} earnings summary is ready", body=..., link=<frontend earnings page>, dedupe_key=f"attestation_annual_summary:{attestor_id}:{year}")`) — pattern from `attestation/notifications.py:_dispatch`. **Link points at the app earnings page, never a presigned URL.**

- [ ] **Step 6: Add the Beat schedule entry**

In `beat_schedule.py` add:
```python
"generate-annual-earnings-summaries-yearly": {
    "task": "app.workers.tasks.invoicing_beat.generate_annual_earnings_summaries",
    "schedule": crontab(month_of_year=1, day_of_month=2, hour=6, minute=0),
},
```

- [ ] **Step 7: Add the fetch endpoint + test**

`get_annual_summary(db, *, user, year)`: `key = annual_summary_key(user.id, year)`; if `s3.storage.object_exists(bucket, key)` → 302 presigned; else 404 ("No earnings summary for that year."). Route `GET /attestations/earnings/annual/{year}` gated by `require_approved_attestor` (own summary only — `user.id` is the key, no cross-user access). Test: attestor with a generated 2026 summary → 302; another attestor → 404 (their own key absent); non-attestor role → 403 (dependency).

- [ ] **Step 8: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/workers/tasks/invoicing_beat.py backend/app/modules/invoicing/annual.py backend/app/workers/beat_schedule.py backend/app/modules/attestation/document_service.py backend/app/modules/attestation/router.py backend/tests
git commit -m "Add annual attestor earnings summary Beat job + fetch endpoint (6d)"
```

---

### Task 7: OpenAPI contract

**Files:**
- Modify: `contracts/openapi.yaml` — add the three attestation document endpoints.

**Interfaces:**
- Consumes: the endpoints from Tasks 4–6 (paths, responses).
- Produces: contract entries for `GET /v1/attestations/{attestation_id}/invoice`, `GET /v1/attestations/{attestation_id}/earnings-statement`, `GET /v1/attestations/earnings/annual/{year}`.

- [ ] **Step 1: Read neighbouring attestation paths in the contract**

Run: `cd backend && grep -n "attestations/{attestation_id}" ../contracts/openapi.yaml | head`
Match the existing style (tags, security, param schema, 302/202/409/403/404 responses). The purchase-invoice entry (`/financials/purchases/{transaction_id}/invoice`) is the closest existing analog for the 302/202 response shape — mirror it.

- [ ] **Step 2: Add the three paths**

Add each with: `get` op, `tags: [Attestation]`, bearer security, `attestation_id`/`year` path params, responses `302` (redirect), `202` (`InvoiceGenerationResponse`-like), `403`, `404`, and `409` (invoice/earnings only). Reference/define the 202 body schema consistent with what the endpoints return.

- [ ] **Step 3: Validate the contract**

Run the repo's OpenAPI lint/validation step if one exists (check CI config / `make` targets, e.g. `grep -rn openapi Makefile .github/`). Otherwise validate YAML loads: `cd backend && uv run python -c "import yaml; yaml.safe_load(open('../contracts/openapi.yaml'))"`.
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add contracts/openapi.yaml
git commit -m "Add OpenAPI contract for attestation invoice, earnings statement, annual summary (6d)"
```

---

## Final verification (after all tasks)

- [ ] Full backend suite: `cd backend && DATABASE_URL="postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test" uv run pytest -q` → 0 failures.
- [ ] `alembic upgrade head` then `alembic downgrade -1` then `upgrade head` all succeed.
- [ ] `cd backend && uv run ruff check . && uv run mypy app` → clean.
- [ ] Spot-check: a settled attestation yields a requestor tax invoice (AUR-INV) and an attestor earnings statement (AUR-ERN) with the same fee; numbers gapless; annual Beat run (freezegun) produces per-earner PDFs + notifications; purchase invoice still works and is now AUR-INV numbered.
