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

describe("FrameworkForm free listings", () => {
  it("submits a zero price when the free toggle is checked", async () => {
    const onSubmit = vi.fn(async (_payload: unknown) => undefined);
    const { container } = render(<FrameworkForm onSubmit={onSubmit} />);

    fireEvent.click(screen.getByLabelText(/offer this framework free/i));
    fireEvent.submit(container.querySelector("form") as HTMLFormElement);

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      pricing: { price: "0.00" },
    });
  });

  it("removes the amount field while the Framework is free", () => {
    // Not merely disabled: the field carries a "Base Price *" label and a
    // `required` input, so leaving it on screen reads as the form still asking
    // for a price the Contributor has just said is not being charged. QA
    // reported exactly that.
    render(<FrameworkForm onSubmit={async () => undefined} />);

    expect(screen.getByLabelText(/^base price/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/offer this framework free/i));

    expect(screen.queryByLabelText(/^base price/i)).not.toBeInTheDocument();
  });

  it("restores a typed amount when the free toggle is unchecked", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    fireEvent.change(screen.getByLabelText(/^base price/i), {
      target: { value: "250.00" },
    });
    const toggle = screen.getByLabelText(/offer this framework free/i);
    fireEvent.click(toggle);
    fireEvent.click(toggle);

    expect(screen.getByLabelText(/^base price/i)).toHaveValue("250.00");
  });

  it("prices the organization tier free while the base tier stays paid", async () => {
    const onSubmit = vi.fn(async (_payload: unknown) => undefined);
    const { container } = render(<FrameworkForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText(/^base price/i), {
      target: { value: "250.00" },
    });
    fireEvent.click(screen.getByLabelText(/^organizational$/i));
    fireEvent.click(screen.getByLabelText(/organization tier is free/i));
    fireEvent.submit(container.querySelector("form") as HTMLFormElement);

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      pricing: { price: "250.00", org_price: "0.00" },
    });
  });
});
