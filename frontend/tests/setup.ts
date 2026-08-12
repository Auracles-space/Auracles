import "@testing-library/jest-dom/vitest";

// The suite runs on USD while the pilot deployment runs on NGN. Pinned here for
// the same reason the backend pins it in tests/conftest.py: payout components
// pick their rail from this value, so leaving it unset would silently route
// every existing Stripe-rail test through Paystack. NGN-specific behaviour is
// covered by tests that select Nigeria explicitly, which routes on country
// regardless of this setting.
process.env.NEXT_PUBLIC_PLATFORM_CURRENCY = "USD";
