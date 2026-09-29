/**
 * Provider routing in Collection bundle checkout.
 *
 * Bundles route by currency and country exactly as single Frameworks do, but
 * this form sent no country and read only `client_secret`, so in the platform's
 * own settlement currency it showed "Checkout could not be started." on a
 * perfectly good Paystack response. A bundle could be listed and priced and
 * never bought.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionCheckoutForm } from "@/components/modules/financials/checkout-form";
import { getExploreCollectionDetail } from "@/lib/generated/sdk.gen";
import type { ExploreCollectionDetail } from "@/lib/generated/types.gen";
import { startCollectionPurchase } from "@/lib/marketplace/purchase-context";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve({})),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getExploreCollectionDetail: vi.fn(),
}));

vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="stripe-elements">{children}</div>
  ),
  PaymentElement: () => <div data-testid="payment-element" />,
  useElements: vi.fn(() => ({})),
  useStripe: vi.fn(() => ({ confirmPayment: vi.fn() })),
}));

vi.mock("@/lib/marketplace/purchase-context", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/marketplace/purchase-context")
  >("@/lib/marketplace/purchase-context");
  return { ...actual, startCollectionPurchase: vi.fn() };
});

const collection: ExploreCollectionDetail = {
  already_owned_member_ids: [],
  bundle_price: "400000.00",
  contributor_id: "00000000-0000-4000-8000-000000000014",
  contributor_name: "Mara Okafor",
  created_at: "2026-06-09T00:00:00Z",
  currency: "NGN",
  description: "A bundle of diligence controls for an operating team.",
  id: "00000000-0000-4000-8000-000000000020",
  item_type: "collection",
  member_count: 1,
  member_price_sum: "500000.00",
  members: [
    {
      category: "playbook",
      currency: "NGN",
      framework_id: "00000000-0000-4000-8000-000000000021",
      price: "500000.00",
      thumbnail_key: null,
      title: "Diligence Control Playbook",
      version: "1.0.0",
    },
  ],
  savings_amount: "100000.00",
  savings_percent: "20.00",
  title: "Diligence Control Collection",
  updated_at: "2026-06-09T00:00:00Z",
};

describe("CollectionCheckoutForm provider routing", () => {
  beforeEach(() => {
    vi.mocked(getExploreCollectionDetail).mockResolvedValue({
      data: collection,
      response: { ok: true } as Response,
    } as never);
  });

  it("sends the chosen billing country so the rail can be decided", async () => {
    vi.mocked(startCollectionPurchase).mockResolvedValue({
      kind: "stripe",
      clientSecret: "pi_secret",
      transactionId: "00000000-0000-4000-8000-000000000030",
    });

    render(<CollectionCheckoutForm collection={collection} />);
    fireEvent.change(await screen.findByLabelText(/billing country/i), {
      target: { value: "NG" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start checkout" }));

    await waitFor(() => {
      expect(startCollectionPurchase).toHaveBeenCalledWith(
        expect.objectContaining({ country: "NG" }),
      );
    });
  });

  it("navigates to Paystack rather than mounting an empty card form", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign, origin: "https://auracles.space", search: "" },
    });
    vi.mocked(startCollectionPurchase).mockResolvedValue({
      kind: "paystack",
      authorizationUrl: "https://checkout.paystack.com/ref_bundle",
      transactionId: "00000000-0000-4000-8000-000000000030",
    });

    render(<CollectionCheckoutForm collection={collection} />);
    fireEvent.click(screen.getByRole("button", { name: "Start checkout" }));

    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith(
        "https://checkout.paystack.com/ref_bundle",
      );
    });
    expect(screen.queryByTestId("payment-element")).toBeNull();
    // The button must stay disabled through navigation: re-enabling it invites
    // a second press and a second charge for the same bundle.
    expect(
      screen.getByRole("button", { name: "Preparing checkout" }),
    ).toBeDisabled();
  });
});
