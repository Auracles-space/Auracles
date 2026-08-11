import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CheckoutForm } from "@/components/modules/financials/checkout-form";
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
  useStripe: vi.fn(() => ({
    confirmPayment: vi.fn(),
  })),
}));

vi.mock("@/lib/marketplace/purchase-context", async () => {
  const actual = await vi.importActual<typeof import("@/lib/marketplace/purchase-context")>(
    "@/lib/marketplace/purchase-context",
  );
  return {
    ...actual,
    startPurchase: vi.fn(),
  };
});

const baseFramework = {
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
  lifecycle_stage: "growth",
  org_price: "900.00",
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
} as const;

describe("CheckoutForm org tier coupling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(startPurchase).mockResolvedValue({
      kind: "stripe",
      clientSecret: "pi_secret_checkout",
      transactionId: "00000000-0000-4000-8000-000000000099",
    });
  });

  it("hides buyer selection and license radios for a single-user-only framework", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue({
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Acme", type: "company" },
            role: "admin",
            capabilities: { operator: "active" },
          },
        ],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    } as never);

    render(
      <CheckoutForm
        framework={{ ...baseFramework, license_types: ["single_user"], org_price: null } as never}
      />,
    );

    await waitFor(() => {
      expect(listMyOrganizationsV1OrgsMineGet).toHaveBeenCalled();
    });

    expect(screen.queryByText(/purchase as/i)).toBeNull();
    expect(screen.queryByLabelText(/single user/i)).toBeNull();
    expect(screen.queryByLabelText(/organizational/i)).toBeNull();
  });

  it("selects the org buyer, shows the org price, and sends organizational licensing", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue({
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Acme", type: "company" },
            role: "admin",
            capabilities: { operator: "active" },
          },
        ],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    } as never);

    render(
      <CheckoutForm
        framework={{
          ...baseFramework,
          license_types: ["single_user", "organizational"],
        } as never}
      />,
    );

    fireEvent.click(await screen.findByLabelText("Acme"));
    expect(screen.getByText("$900")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start checkout" }));

    await waitFor(() => {
      expect(startPurchase).toHaveBeenCalledWith(
        expect.objectContaining({
          buyer: { kind: "org", orgId: "org-1", label: "Acme" },
          frameworkId: baseFramework.id,
          licenseType: "organizational",
        }),
      );
    });
  });
});
