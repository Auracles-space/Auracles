/**
 * Partner checkout demo tests.
 *
 * The demo is the reference a Partner copies, so it must branch on the rail the
 * Partner API returns rather than assuming Stripe. Sending a Paystack buyer to
 * an unmounted card form is what stranded every Nigerian purchase before the
 * routing fix.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PartnerCheckoutDemo } from "@/components/modules/developer/partner-checkout-demo";

vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="stripe-elements">{children}</div>
  ),
  PaymentElement: () => <div data-testid="payment-element" />,
  useElements: () => null,
  useStripe: () => null,
}));

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: () => Promise.resolve(null),
}));

/** Drive the form as far as the provider handoff. */
async function startCheckout(purchaseResponse: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/purchase")) {
      return {
        ok: true,
        status: 200,
        json: async () => purchaseResponse,
      } as Response;
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        title: "Nigerian Market Entry Framework",
        price: "400000.00",
        currency: "NGN",
      }),
    } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<PartnerCheckoutDemo />);
  fireEvent.change(screen.getByPlaceholderText("ak_…"), {
    target: { value: "ak_partner_demo_key" },
  });
  fireEvent.change(
    screen.getByPlaceholderText("00000000-0000-0000-0000-000000000000"),
    { target: { value: "5f1d4d0e-0d6e-4f1a-9a2f-2b6c1f0a77aa" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Load framework" }));
  await screen.findByText("Nigerian Market Entry Framework");
  fireEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
  return fetchMock;
}

describe("PartnerCheckoutDemo", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("redirects the buyer to Paystack when that is the rail", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        origin: "https://partner.example.com",
        search: "",
        set href(value: string) {
          assign(value);
        },
      },
    });

    await startCheckout({
      transaction_id: "b2a6f2c0-3d1e-4a5b-8c7d-9e0f1a2b3c4d",
      provider: "paystack",
      authorization_url: "https://checkout.paystack.com/ref_demo",
      client_secret: null,
    });

    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith(
        "https://checkout.paystack.com/ref_demo",
      );
    });
    // Stripe's form must never appear on this rail: mounting Elements against a
    // null client secret is exactly the stranded checkout this branch prevents.
    expect(screen.queryByTestId("payment-element")).toBeNull();
  });

  it("mounts the card form when the rail is Stripe", async () => {
    await startCheckout({
      transaction_id: "b2a6f2c0-3d1e-4a5b-8c7d-9e0f1a2b3c4d",
      provider: "stripe",
      client_secret: "pi_demo_secret",
      authorization_url: null,
    });

    expect(await screen.findByTestId("payment-element")).toBeInTheDocument();
  });

  it("explains a Paystack handoff that arrives without a URL", async () => {
    await startCheckout({
      transaction_id: "b2a6f2c0-3d1e-4a5b-8c7d-9e0f1a2b3c4d",
      provider: "paystack",
      authorization_url: null,
      client_secret: null,
    });

    expect(
      await screen.findByText(
        "Paystack checkout did not return an authorization URL.",
      ),
    ).toBeInTheDocument();
  });

  it("confirms a Paystack buyer who returns on the platform's own param", async () => {
    // Paystack sends the buyer back to the return URL with `purchase=`
    // appended. The demo used to read `paid=`, which only its own Stripe
    // branch set, so a buyer who had paid landed back on the empty form.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        origin: "https://partner.example.com",
        search: "?purchase=b2a6f2c0-3d1e-4a5b-8c7d-9e0f1a2b3c4d&trxref=T1121",
        href: "",
      },
    });

    render(<PartnerCheckoutDemo />);

    expect(screen.getByText("Payment complete")).toBeInTheDocument();
    expect(
      screen.getByText("b2a6f2c0-3d1e-4a5b-8c7d-9e0f1a2b3c4d"),
    ).toBeInTheDocument();
  });
});
