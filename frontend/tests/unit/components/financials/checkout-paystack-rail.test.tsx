/**
 * Unit coverage for provider routing in Operator checkout.
 *
 * The billing country decides which rail settles the charge, so these tests
 * pin the two behaviours that decision produces: the country reaches the API,
 * and a Paystack response navigates to the hosted page instead of mounting
 * Stripe Elements against a client secret that does not exist.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CheckoutForm } from "@/components/modules/financials/checkout-form";
import type { ExploreFrameworkDetail } from "@/lib/generated/types.gen";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";
import { startPurchase } from "@/lib/marketplace/purchase-context";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve({})),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
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
  return { ...actual, startPurchase: vi.fn() };
});

const framework: ExploreFrameworkDetail = {
  attestation_badge: null,
  attestation_badges: [],
  artifacts: [],
  average_review_score: null,
  category: "playbook",
  complexity: 3,
  contributor_id: "00000000-0000-4000-8000-000000000014",
  contributor_name: "Mara Okafor",
  contributor_org_id: null,
  contributor_reputation_score: null,
  contributor_slug: "mara-okafor",
  contributor_verification_level: null,
  currency: "USD",
  description: "Operator-ready controls for diligence workstreams.",
  function: "governance",
  id: "00000000-0000-4000-8000-000000000013",
  industry: "fund_management",
  jurisdiction: "US",
  license_types: ["single_user"],
  lifecycle_stage: "growth",
  org_price: null,
  org_size: "mid_market",
  owned: false,
  preview_artifact_id: null,
  preview_url: null,
  price: "250.00",
  published_at: "2026-06-09T00:00:00Z",
  rarity_score: "0.82",
  reputation: null,
  review_count: 0,
  sector: "private_equity",
  tags: ["diligence", "controls"],
  thumbnail_key: null,
  title: "Diligence Control Playbook",
  version: "1.0.0",
};

describe("CheckoutForm payment rail routing", () => {
  const assign = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue({
      data: { organizations: [] },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    } as never);
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { origin: "http://testserver", assign },
    });
  });

  it("sends the selected billing country so the backend can pick a rail", async () => {
    vi.mocked(startPurchase).mockResolvedValue({
      kind: "stripe",
      clientSecret: "pi_secret_checkout",
      transactionId: "00000000-0000-4000-8000-000000000099",
    });
    render(<CheckoutForm framework={framework} />);

    fireEvent.change(await screen.findByLabelText(/billing country/i), {
      target: { value: "NG" },
    });
    fireEvent.click(screen.getByRole("button", { name: /start checkout/i }));

    await waitFor(() => {
      expect(vi.mocked(startPurchase)).toHaveBeenCalledWith(
        expect.objectContaining({ country: "NG" }),
      );
    });
  });

  it("redirects to the hosted page for a Paystack purchase", async () => {
    vi.mocked(startPurchase).mockResolvedValue({
      kind: "paystack",
      authorizationUrl: "https://checkout.paystack.com/auracles_ref_123",
      transactionId: "00000000-0000-4000-8000-000000000099",
    });
    render(<CheckoutForm framework={framework} />);

    fireEvent.click(
      await screen.findByRole("button", { name: /start checkout/i }),
    );

    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith(
        "https://checkout.paystack.com/auracles_ref_123",
      );
    });
    // Elements must never mount on this rail: there is no client secret to
    // give it, and a mounted card form would collect details twice.
    expect(screen.queryByTestId("stripe-elements")).toBeNull();
  });

  it("keeps mounting Stripe Elements for a Stripe purchase", async () => {
    vi.mocked(startPurchase).mockResolvedValue({
      kind: "stripe",
      clientSecret: "pi_secret_checkout",
      transactionId: "00000000-0000-4000-8000-000000000099",
    });
    render(<CheckoutForm framework={framework} />);

    fireEvent.click(
      await screen.findByRole("button", { name: /start checkout/i }),
    );

    expect(await screen.findByTestId("stripe-elements")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });
});
