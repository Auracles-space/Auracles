import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CheckoutForm } from "@/components/modules/financials/checkout-form";
import { createFrameworkPurchase } from "@/lib/generated/sdk.gen";
import type { ExploreFrameworkDetail } from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve({})),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createFrameworkPurchase: vi.fn(),
}));

vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="stripe-elements">{children}</div>
  ),
  PaymentElement: () => <div data-testid="payment-element" />,
  useElements: vi.fn(() => ({})),
  useStripe: vi.fn(() => ({
    confirmPayment: vi.fn(),
  })),
}));

const framework: ExploreFrameworkDetail = {
  attestation_badge: null,
  artifacts: [],
  average_review_score: null,
  category: "playbook",
  complexity: 3,
  currency: "USD",
  description: "Operator-ready controls for diligence workstreams.",
  function: "governance",
  id: "00000000-0000-4000-8000-000000000013",
  industry: "fund_management",
  jurisdiction: "US",
  lifecycle_stage: "growth",
  license_types: ["single_user", "team", "organizational"],
  org_size: "mid_market",
  owned: false,
  preview_artifact_id: null,
  preview_url: null,
  price: "250.00",
  published_at: "2026-06-09T00:00:00Z",
  rarity_score: "0.82",
  review_count: 0,
  sector: "private_equity",
  tags: ["diligence", "controls"],
  thumbnail_key: null,
  title: "Diligence Control Playbook",
  version: "1.0.0",
};

describe("CheckoutForm", () => {
  beforeEach(() => {
    vi.mocked(createFrameworkPurchase).mockReset();
  });

  it("starts checkout for the selected self-serve license", async () => {
    vi.mocked(createFrameworkPurchase).mockResolvedValue({
      data: {
        client_secret: "pi_secret_checkout",
        provider: "stripe",
        transaction_id: "00000000-0000-4000-8000-000000000099",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<CheckoutForm framework={framework} />);

    fireEvent.click(screen.getByLabelText("Team"));
    fireEvent.click(screen.getByRole("button", { name: "Start checkout" }));

    await waitFor(() => {
      expect(createFrameworkPurchase).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { license_type: "team" },
          path: { framework_id: framework.id },
        }),
      );
    });
    expect(await screen.findByTestId("payment-element")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirm payment" }),
    ).toBeInTheDocument();
  });
});
