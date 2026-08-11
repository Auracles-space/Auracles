import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CheckoutForm,
  CollectionCheckoutForm,
} from "@/components/modules/financials/checkout-form";
import {
  createCollectionPurchase,
  createFrameworkPurchase,
  getExploreCollectionDetail,
  listMyOrganizationsV1OrgsMineGet,
} from "@/lib/generated/sdk.gen";
import type {
  ExploreCollectionDetail,
  ExploreFrameworkDetail,
} from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve({})),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createCollectionPurchase: vi.fn(),
  createFrameworkPurchase: vi.fn(),
  getExploreCollectionDetail: vi.fn(),
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

const framework: ExploreFrameworkDetail = {
  attestation_badge: null,
  artifacts: [],
  average_review_score: null,
  category: "playbook",
  complexity: 3,
  contributor_id: "00000000-0000-4000-8000-000000000014",
  contributor_name: "Mara Okafor",
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

const collection: ExploreCollectionDetail = {
  already_owned_member_ids: ["00000000-0000-4000-8000-000000000021"],
  bundle_price: "700.00",
  contributor_id: "00000000-0000-4000-8000-000000000014",
  contributor_name: "Mara Okafor",
  created_at: "2026-06-09T00:00:00Z",
  currency: "USD",
  description: "A bundle of diligence controls for an operating team.",
  id: "00000000-0000-4000-8000-000000000020",
  item_type: "collection",
  member_count: 3,
  member_price_sum: "900.00",
  members: [
    {
      category: "playbook",
      currency: "USD",
      framework_id: "00000000-0000-4000-8000-000000000021",
      price: "250.00",
      thumbnail_key: null,
      title: "Diligence Control Playbook",
      version: "1.0.0",
    },
    {
      category: "checklist",
      currency: "USD",
      framework_id: "00000000-0000-4000-8000-000000000022",
      price: "300.00",
      thumbnail_key: null,
      title: "Risk Register Checklist",
      version: "1.0.0",
    },
    {
      category: "template",
      currency: "USD",
      framework_id: "00000000-0000-4000-8000-000000000023",
      price: "350.00",
      thumbnail_key: null,
      title: "Control Evidence Template",
      version: "1.0.0",
    },
  ],
  savings_amount: "200.00",
  savings_percent: "22.22",
  title: "Diligence Control Collection",
  updated_at: "2026-06-09T00:00:00Z",
};

describe("CheckoutForm", () => {
  beforeEach(() => {
    vi.mocked(createCollectionPurchase).mockReset();
    vi.mocked(createFrameworkPurchase).mockReset();
    vi.mocked(getExploreCollectionDetail).mockReset();
    vi.mocked(getExploreCollectionDetail).mockResolvedValue({
      data: collection,
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue({
      data: {
        organizations: [
          {
            org: { id: "00000000-0000-4000-8000-0000000000org", name: "Test Org", type: "company" },
            role: "admin",
            capabilities: { operator: "active" },
          },
        ],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
  });

  it("starts checkout for the default self purchase license", async () => {
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

    fireEvent.click(screen.getByRole("button", { name: "Start checkout" }));

    await waitFor(() => {
      expect(createFrameworkPurchase).toHaveBeenCalledWith(
        expect.objectContaining({
          // Country is always sent: it selects the payment rail, and omitting
          // it would silently settle a Nigerian buyer on Stripe.
          body: { license_type: "single_user", country: expect.any(String) },
          path: { framework_id: framework.id },
        }),
      );
    });
    expect(await screen.findByTestId("payment-element")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirm payment" }),
    ).toBeInTheDocument();
  });

  it("renders buyer options from a wrapper payload", async () => {
    render(<CheckoutForm framework={framework} />);
    
    // The default option "Myself" should be present
    expect(await screen.findByText("Myself")).toBeInTheDocument();
    
    // The "Test Org" from the mock listMyOrganizationsV1OrgsMineGet response should also be present
    expect(await screen.findByText("Test Org")).toBeInTheDocument();
  });

  it("starts checkout for a collection bundle", async () => {
    vi.mocked(createCollectionPurchase).mockResolvedValue({
      data: {
        client_secret: "pi_secret_collection",
        provider: "stripe",
        transaction_id: "00000000-0000-4000-8000-000000000098",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<CollectionCheckoutForm collection={collection} />);

    fireEvent.click(screen.getByLabelText("Team"));
    fireEvent.click(screen.getByRole("button", { name: "Start checkout" }));

    await waitFor(() => {
      expect(createCollectionPurchase).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { license_type: "team" },
          path: { collection_id: collection.id },
        }),
      );
    });
    expect(screen.getByText("Includes")).toBeInTheDocument();
    expect(screen.getByText("3 frameworks")).toBeInTheDocument();
    expect(screen.getByText("Already own")).toBeInTheDocument();
    expect(screen.getByText("1 member")).toBeInTheDocument();
    expect(await screen.findByTestId("payment-element")).toBeInTheDocument();
  });
});
