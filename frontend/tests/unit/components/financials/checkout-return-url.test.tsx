import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CheckoutForm } from "@/components/modules/financials/checkout-form";
import * as sdk from "@/lib/generated/sdk.gen";

const confirmPayment = vi.fn().mockResolvedValue({ error: undefined });

vi.mock("@/lib/auth/form-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/form-client")>(
    "@/lib/auth/form-client",
  );
  return {
    ...actual,
    configureBrowserClient: vi.fn(),
    describeGeneratedError: vi.fn(() => "err"),
    getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
  };
});
vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve({})),
}));
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PaymentElement: () => <div />,
  useElements: () => ({}),
  useStripe: () => ({ confirmPayment }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  createFrameworkPurchase: vi.fn(),
  createOrgFrameworkPurchase: vi.fn(),
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
  getExploreCollectionDetail: vi.fn(),
}));

const framework = {
  id: "fw",
  license_types: ["organizational"],
  price: 1000,
  currency: "USD",
} as never;
const ok = <T,>(d: T) => ({
  data: d,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

async function startCheckoutAs(orgName: string | null): Promise<void> {
  render(<CheckoutForm framework={framework} />);
  if (orgName) {
    await waitFor(() => screen.getByRole("radio", { name: new RegExp(orgName, "i") }));
    fireEvent.click(screen.getByRole("radio", { name: new RegExp(orgName, "i") }));
  } else {
    await waitFor(() =>
      expect(sdk.listMyOrganizationsV1OrgsMineGet).toHaveBeenCalled(),
    );
  }
  fireEvent.click(screen.getByRole("button", { name: /start checkout/i }));
  await screen.findByRole("button", { name: /confirm payment/i });
  fireEvent.click(screen.getByRole("button", { name: /confirm payment/i }));
}

describe("CheckoutForm success redirect", () => {
  beforeEach(() => vi.clearAllMocks());

  it("returns an org buyer to the org operator library", async () => {
    vi.mocked(sdk.listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({
        organizations: [
          {
            org: { id: "org-1", name: "Acme" },
            role: "admin",
            capabilities: { operator: "active" },
          },
        ],
      }) as never,
    );
    vi.mocked(sdk.createOrgFrameworkPurchase).mockResolvedValue(
      ok({ client_secret: "cs", transaction_id: "tx" }) as never,
    );

    await startCheckoutAs("Acme");

    await waitFor(() => expect(confirmPayment).toHaveBeenCalled());
    const returnUrl = confirmPayment.mock.calls[0][0].confirmParams.return_url;
    expect(returnUrl).toContain("/dashboard/organizations/org-1/operator/library");
    expect(returnUrl).toContain("purchase=tx");
  });

  it("returns a self buyer to the personal library", async () => {
    vi.mocked(sdk.listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [] }) as never,
    );
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue(
      ok({ client_secret: "cs", transaction_id: "tx" }) as never,
    );

    await startCheckoutAs(null);

    await waitFor(() => expect(confirmPayment).toHaveBeenCalled());
    const returnUrl = confirmPayment.mock.calls[0][0].confirmParams.return_url;
    expect(returnUrl).toContain("/library?purchase=tx");
    expect(returnUrl).not.toContain("/organizations/");
  });
});
