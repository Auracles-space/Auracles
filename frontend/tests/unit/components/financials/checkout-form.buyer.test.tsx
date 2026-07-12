import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CheckoutForm } from "@/components/modules/financials/checkout-form";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/form-client")>("@/lib/auth/form-client");
  return {
    ...actual,
    configureBrowserClient: vi.fn(),
    describeGeneratedError: vi.fn(() => "err"),
    getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
  };
});
vi.mock("@/lib/financials/stripe-client", () => ({ getStripeClient: vi.fn(() => Promise.resolve(null)) }));
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PaymentElement: () => <div />,
  useElements: () => null,
  useStripe: () => null,
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  createFrameworkPurchase: vi.fn(),
  createOrgFrameworkPurchase: vi.fn(),
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
  getExploreCollectionDetail: vi.fn(),
}));

const framework = { id: "fw", license_types: ["organizational"], price: 1000, currency: "USD" } as never;
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("CheckoutForm buyer context", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the buyer selector when an eligible org exists and routes the org purchase", async () => {
    vi.mocked(sdk.listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [{ org: { id: "org-1", name: "Acme" }, role: "admin", capabilities: { operator: "active" } }] }) as never,
    );
    vi.mocked(sdk.createOrgFrameworkPurchase).mockResolvedValue(ok({ client_secret: "cs", transaction_id: "tx" }) as never);

    render(<CheckoutForm framework={framework} />);
    await waitFor(() => screen.getByRole("radio", { name: /acme/i }));

    screen.getByRole("radio", { name: /acme/i }).click();
    screen.getByRole("button", { name: /pay|start checkout|license this framework/i }).click();

    await waitFor(() =>
      expect(sdk.createOrgFrameworkPurchase).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1", framework_id: "fw" } }),
      ),
    );
  });

  it("hides the buyer selector when there are no eligible orgs", async () => {
    vi.mocked(sdk.listMyOrganizationsV1OrgsMineGet).mockResolvedValue(ok({ organizations: [] }) as never);
    render(<CheckoutForm framework={framework} />);
    await waitFor(() => expect(sdk.listMyOrganizationsV1OrgsMineGet).toHaveBeenCalled());
    expect(screen.queryByText(/purchase as/i)).toBeNull();
  });
});
