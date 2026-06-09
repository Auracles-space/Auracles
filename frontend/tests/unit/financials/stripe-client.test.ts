import { beforeEach, describe, expect, it, vi } from "vitest";

const stripeMocks = vi.hoisted(() => ({
  loadStripe: vi.fn(async (key: string) => ({ publishableKey: key })),
}));

vi.mock("@stripe/stripe-js", () => ({
  loadStripe: stripeMocks.loadStripe,
}));

describe("stripe browser client", () => {
  beforeEach(() => {
    vi.resetModules();
    stripeMocks.loadStripe.mockClear();
    delete process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;
  });

  it("loads Stripe once with the configured publishable key", async () => {
    process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY = "pk_test_auracles";
    const { getStripeClient } = await import("@/lib/financials/stripe-client");

    const firstClient = getStripeClient();
    const secondClient = getStripeClient();

    expect(firstClient).toBe(secondClient);
    await expect(firstClient).resolves.toEqual({
      publishableKey: "pk_test_auracles",
    });
    expect(stripeMocks.loadStripe).toHaveBeenCalledTimes(1);
    expect(stripeMocks.loadStripe).toHaveBeenCalledWith("pk_test_auracles");
  });

  it("rejects missing or secret Stripe keys before loading Stripe.js", async () => {
    const missingKey = await import("@/lib/financials/stripe-client");

    expect(() => missingKey.getStripePublishableKey()).toThrow(
      "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY is required.",
    );

    vi.resetModules();
    process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY = "sk_test_never_browser";
    const secretKey = await import("@/lib/financials/stripe-client");

    expect(() => secretKey.getStripeClient()).toThrow(
      "Stripe browser code requires a publishable key.",
    );
    expect(stripeMocks.loadStripe).not.toHaveBeenCalled();
  });
});
