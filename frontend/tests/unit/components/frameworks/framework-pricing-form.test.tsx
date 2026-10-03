import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FrameworkPricingForm } from "@/components/modules/frameworks/framework-pricing-form";
import type { FrameworkApi } from "@/lib/frameworks/framework-api";
import type { FrameworkResponse } from "@/lib/generated/types.gen";

/** Minimal org framework with pricing for the form under test. */
const framework = {
  id: "fw_1",
  pricing: {
    price: "499.00",
    org_price: null,
    currency: "USD",
    license_types: ["single_user"],
    commercial_rights: "Internal use allowed.",
    usage_restrictions: "No resale.",
  },
} as unknown as FrameworkResponse;

/** Framework API adapter double exposing only the pricing action. */
const api = { updatePricing: vi.fn() } as unknown as FrameworkApi;

describe("FrameworkPricingForm", () => {
  it("keeps Save pricing disabled until a field changes", () => {
    render(
      <FrameworkPricingForm api={api} framework={framework} onUpdated={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: /save pricing/i })).toBeDisabled();
  });

  it("enables Save pricing once the base price is edited", () => {
    render(
      <FrameworkPricingForm api={api} framework={framework} onUpdated={vi.fn()} />,
    );

    fireEvent.change(screen.getByLabelText(/base price/i), {
      target: { value: "550.00" },
    });

    expect(
      screen.getByRole("button", { name: /save pricing/i }),
    ).toBeEnabled();
  });

  it("re-disables Save pricing when edits are reverted to the saved values", () => {
    render(
      <FrameworkPricingForm api={api} framework={framework} onUpdated={vi.fn()} />,
    );

    const priceInput = screen.getByLabelText(/base price/i);
    fireEvent.change(priceInput, { target: { value: "550.00" } });
    fireEvent.change(priceInput, { target: { value: "499.00" } });

    expect(screen.getByRole("button", { name: /save pricing/i })).toBeDisabled();
  });

  it("enables Save pricing when a license type is toggled", () => {
    render(
      <FrameworkPricingForm api={api} framework={framework} onUpdated={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /organization/i }));

    expect(screen.getByRole("button", { name: /save pricing/i })).toBeEnabled();
  });
});

describe("FrameworkPricingForm free listings", () => {
  it("removes the base price field when the free toggle is checked", () => {
    // A greyed-out field under a "Base price" label still reads as the form
    // asking for a price the seller has just said is not being charged.
    render(
      <FrameworkPricingForm api={api} framework={framework} onUpdated={vi.fn()} />,
    );

    expect(screen.getByLabelText(/base price/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/offer this framework free/i));

    expect(screen.queryByLabelText(/base price/i)).not.toBeInTheDocument();
  });

  it("restores the previous amount when the free toggle is unchecked", () => {
    // Someone trying the toggle to see what it does must not lose the price
    // they already typed.
    render(
      <FrameworkPricingForm api={api} framework={framework} onUpdated={vi.fn()} />,
    );

    const toggle = screen.getByLabelText(/offer this framework free/i);
    fireEvent.click(toggle);
    fireEvent.click(toggle);

    const priceInput = screen.getByLabelText(/base price/i);
    expect(priceInput).toBeEnabled();
    expect(priceInput).toHaveValue("499.00");
  });

  it("saves a free Framework as a zero price", async () => {
    const onUpdated = vi.fn();
    vi.mocked(api.updatePricing).mockResolvedValue(framework);
    render(
      <FrameworkPricingForm api={api} framework={framework} onUpdated={onUpdated} />,
    );

    fireEvent.click(screen.getByLabelText(/offer this framework free/i));
    fireEvent.click(screen.getByRole("button", { name: /save pricing/i }));

    await vi.waitFor(() => {
      expect(api.updatePricing).toHaveBeenCalledWith(
        "fw_1",
        expect.objectContaining({
          pricing: expect.objectContaining({ price: "0.00" }),
        }),
      );
    });
  });

  it("prices the organization tier free independently of the base price", async () => {
    // Free for individuals, paid for Organizations is the shape this exists
    // for, so the two toggles must not be wired together.
    const orgTierFramework = {
      ...framework,
      pricing: {
        ...framework.pricing,
        license_types: ["single_user", "organizational"],
      },
    } as unknown as FrameworkResponse;
    vi.mocked(api.updatePricing).mockResolvedValue(orgTierFramework);
    render(
      <FrameworkPricingForm
        api={api}
        framework={orgTierFramework}
        onUpdated={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText(/organization tier is free/i));
    fireEvent.click(screen.getByRole("button", { name: /save pricing/i }));

    await vi.waitFor(() => {
      expect(api.updatePricing).toHaveBeenCalledWith(
        "fw_1",
        expect.objectContaining({
          pricing: expect.objectContaining({
            price: "499.00",
            org_price: "0.00",
          }),
        }),
      );
    });
    expect(screen.getByLabelText(/base price/i)).toBeEnabled();
  });
});
