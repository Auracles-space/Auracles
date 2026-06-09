import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PaymentMethodList } from "@/components/modules/financials/payment-method-list";
import {
  createPaymentMethodSetup,
  deletePaymentMethod,
  listPaymentMethods,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve({})),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createPaymentMethodSetup: vi.fn(),
  deletePaymentMethod: vi.fn(),
  listPaymentMethods: vi.fn(),
}));

vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="setup-elements">{children}</div>
  ),
  PaymentElement: () => <div data-testid="setup-payment-element" />,
  useElements: vi.fn(() => ({})),
  useStripe: vi.fn(() => ({
    confirmSetup: vi.fn(),
  })),
}));

const paymentMethod = {
  brand: "visa",
  exp_month: 12,
  exp_year: 2030,
  id: "pm_test_123",
  last4: "4242",
  provider: "stripe" as const,
  type: "card",
};

describe("PaymentMethodList", () => {
  beforeEach(() => {
    vi.mocked(createPaymentMethodSetup).mockReset();
    vi.mocked(deletePaymentMethod).mockReset();
    vi.mocked(listPaymentMethods).mockReset();
    vi.mocked(listPaymentMethods).mockResolvedValue({
      data: { payment_methods: [paymentMethod] },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
  });

  it("lists provider-held cards, starts setup, and removes a card with 2FA", async () => {
    vi.mocked(createPaymentMethodSetup).mockResolvedValue({
      data: {
        client_secret: "seti_secret_123",
        provider: "stripe",
        setup_intent_id: "seti_test_123",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(deletePaymentMethod).mockResolvedValue({
      data: {
        payment_method_id: paymentMethod.id,
        provider: "stripe",
        removed: true,
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<PaymentMethodList />);

    expect(await screen.findByText("Visa ending 4242")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Setup 2FA code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start secure setup" }));

    await waitFor(() => {
      expect(createPaymentMethodSetup).toHaveBeenCalledWith(
        expect.objectContaining({ body: { totp_code: "123456" } }),
      );
    });
    expect(await screen.findByTestId("setup-payment-element")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Removal 2FA code"), {
      target: { value: "654321" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove card ending 4242" }));

    await waitFor(() => {
      expect(deletePaymentMethod).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { totp_code: "654321" },
          path: { payment_method_id: paymentMethod.id },
        }),
      );
    });
    expect(screen.queryByText("Visa ending 4242")).not.toBeInTheDocument();
  });
});
