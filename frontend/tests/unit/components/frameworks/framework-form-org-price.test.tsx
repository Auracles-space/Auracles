import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FrameworkForm } from "@/components/modules/frameworks/framework-form";

// The suite pins NEXT_PUBLIC_PLATFORM_CURRENCY to USD (see tests/setup.ts), so
// comparing against the real constant would match a hardcoded "USD" and prove
// nothing. A distinctive value proves the form prices in what it displays.
vi.mock("@/lib/marketplace/currency", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/marketplace/currency")>(
      "@/lib/marketplace/currency",
    );
  return { ...actual, PLATFORM_CURRENCY: "NGN" };
});

describe("FrameworkForm org pricing tier", () => {
  it("omits all inline pricing fields when pricing is managed separately", () => {
    render(
      <FrameworkForm
        onSubmit={async () => undefined}
        pricingInline={false}
      />,
    );

    expect(screen.queryByText(/^license types$/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^base price/i)).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/organization price/i),
    ).not.toBeInTheDocument();
  });

  it("reveals the org price field only when the organizational tier is selected", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    expect(
      screen.queryByLabelText(/organization price/i),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/^organizational$/i));

    expect(screen.getByLabelText(/organization price/i)).toBeInTheDocument();
  });

  it("prices in the currency it displays", async () => {
    // The field already renders a ₦ adornment from PLATFORM_CURRENCY while the
    // submitted body said USD, so a correctly filled form was rejected with
    // "Only NGN amounts are supported."
    const onSubmit = vi.fn(async (_payload: unknown) => undefined);
    const { container } = render(<FrameworkForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText(/^base price/i), {
      target: { value: "250.00" },
    });
    // Submit the form directly: jsdom does not run HTML constraint validation,
    // and the taxonomy selects are irrelevant to what currency is sent.
    fireEvent.submit(container.querySelector("form") as HTMLFormElement);

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      pricing: { currency: "NGN" },
    });
  });
});
