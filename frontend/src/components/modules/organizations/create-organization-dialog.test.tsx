import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CreateOrganizationDialog } from "./create-organization-dialog";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createOrganizationV1OrgsPost: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

describe("CreateOrganizationDialog", () => {
  it("offers the pilot market in the country list", () => {
    // The list was bounded by Stripe Connect, which has no Nigeria — so the
    // pilot market could not register an organization at all, on a platform
    // that already routes its checkout and payouts through Paystack.
    render(<CreateOrganizationDialog onClose={vi.fn()} open />);

    expect(
      screen.getByRole("option", { name: "Nigeria" }),
    ).toBeInTheDocument();
  });

  it("still offers the Stripe Connect countries", () => {
    render(<CreateOrganizationDialog onClose={vi.fn()} open />);

    expect(screen.getByRole("option", { name: "Germany" })).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "United States" }),
    ).toBeInTheDocument();
  });
});
