"""Single platform settlement currency.

Auracles trades in exactly one currency at a time. Frameworks are priced in it,
Operators are charged in it, Contributors earn and are paid out in it, and no
conversion step exists anywhere in the money path.

That is a deliberate constraint, not an oversight. The closed Nigerian pilot has
Nigerian buyers and Nigerian sellers, so naira in equals naira out and an FX rate
would be a number nobody needs. Keeping the currency in one setting — rather than
as a literal repeated across every money guard — means the pilot runs on NGN, a
later market can run on something else, and a future multi-currency model extends
this module instead of unpicking twenty hardcodes.

Every ``currency != ...`` guard in the codebase reads through here.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.integrations.amounts import SUPPORTED_MINOR_UNIT_CURRENCIES

# The platform can only settle a currency its payment adapters can convert to
# minor units. Sourcing the set from the adapters keeps config from accepting a
# currency that would fail at charge time instead of at boot.
SUPPORTED_PLATFORM_CURRENCIES = SUPPORTED_MINOR_UNIT_CURRENCIES


def platform_currency() -> str:
    """Return the platform's configured settlement currency.

    Returns:
        The uppercase ISO 4217 code every money amount is denominated in.
    """
    return get_settings().platform_currency


def normalize_platform_currency(value: str) -> str:
    """Normalize a caller-supplied currency, rejecting anything unsettleable.

    Args:
        value: Currency code from a request body or config row.

    Returns:
        The canonical uppercase code, guaranteed equal to `platform_currency()`.

    Raises:
        ValueError: If the code is not the platform's settlement currency. The
            message names the expected currency so the 422 that wraps it tells
            the caller what to send instead.
    """
    normalized = value.strip().upper()
    expected = platform_currency()
    if normalized != expected:
        raise ValueError(f"Only {expected} amounts are supported.")
    return normalized
