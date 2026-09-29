"""Every module that charges a buyer must decide which rail to charge on.

`integrations/payment_router.select_provider` sends the Nigerian corridor to
Paystack and everything else to Stripe. A service that calls a provider's
charge API without consulting it hardcodes a rail, and in the pilot currency
that produces a payment nobody can complete: Stripe will not render an NGN
intent, so the endpoint returns a client secret and the buyer is stranded.

That is not hypothetical. The Partner purchase endpoint shipped this way and
could not complete a single sale (fixed 2026-09-29). It passed review and CI
because `tests/conftest.py` pins the suite to USD, where Stripe is the correct
answer anyway — so the missing decision changed no assertion anywhere.

A behavioural test cannot cover this: it only ever catches the path someone
thought to write a test for. This asserts the invariant across the codebase.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULES_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules"

# Functions that move money on a specific rail. Calling one is the commitment
# that `select_provider` is supposed to precede.
CHARGE_INITIATORS = frozenset(
    {
        "create_payment_intent",
        "initialize_transaction",
    }
)

# Modules that charge on a fixed rail for a stated reason. Each entry needs the
# reason, not just the path: an allowlist without one is how the next hardcoded
# rail gets waved through.
ROUTING_EXEMPT: dict[str, str] = {
    "organizations/billing_service.py": (
        "Org subscription billing charges a stored payment method, which only "
        "Stripe has; the module documents this at its select_provider import."
    ),
}


def _calls_in(tree: ast.AST) -> set[str]:
    """Return every function name called anywhere in a parsed module."""
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            called.add(func.attr)
        elif isinstance(func, ast.Name):
            called.add(func.id)
    return called


def test_every_charging_module_routes_its_provider() -> None:
    """A module that initiates a charge must also call `select_provider`."""
    offenders: list[str] = []

    for path in sorted(MODULES_ROOT.rglob("*.py")):
        relative = path.relative_to(MODULES_ROOT).as_posix()
        if relative in ROUTING_EXEMPT:
            continue
        called = _calls_in(ast.parse(path.read_text(encoding="utf-8")))
        if called & CHARGE_INITIATORS and "select_provider" not in called:
            offenders.append(relative)

    assert not offenders, (
        "These modules initiate a charge without choosing a payment rail, so "
        "they hardcode one. In the platform's own settlement currency that "
        "produces a payment the buyer cannot complete:\n  "
        + "\n  ".join(offenders)
    )


def test_routing_exemptions_still_apply() -> None:
    """An exempt module must still exist and still initiate a charge.

    Keeps the allowlist from outliving its subject: a stale entry would quietly
    exempt a module that had been rewritten to charge on a hardcoded rail.
    """
    for relative, reason in ROUTING_EXEMPT.items():
        path = MODULES_ROOT / relative
        assert path.exists(), f"Exempt module no longer exists: {relative}"
        assert reason.strip(), f"Exemption without a reason: {relative}"
