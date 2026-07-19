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

    fireEvent.click(screen.getByLabelText(/team/i));

    expect(screen.getByRole("button", { name: /save pricing/i })).toBeEnabled();
  });
});
