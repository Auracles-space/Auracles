/**
 * Payout eligibility checklist tests.
 *
 * The org earnings response explains why a payout cannot be requested; the
 * checklist must show each reason with a link to where it is fixed, and
 * disappear once the org is eligible (spec 2026-09-14 §Slice C).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PayoutEligibilityChecklist } from "./payout-eligibility-checklist";

describe("PayoutEligibilityChecklist", () => {
  it("lists every unmet condition and links the fixable ones", () => {
    render(
      <PayoutEligibilityChecklist
        eligibility={{
          eligible: false,
          reasons: [
            {
              code: "kyb_not_verified",
              message: "Verify your business before requesting payouts.",
              action_path: "/dashboard/organizations/org-1/verification",
            },
            {
              code: "payout_in_progress",
              message: "A payout is already in progress.",
              action_path: null,
            },
          ],
        }}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Before you can request a payout" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Verify your business before requesting payouts."),
    ).toBeInTheDocument();
    expect(screen.getByText("A payout is already in progress.")).toBeInTheDocument();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/verification",
    );
    expect(links[0].className).toContain("min-h-11");
  });

  it("renders nothing when the organization is eligible", () => {
    const { container } = render(
      <PayoutEligibilityChecklist eligibility={{ eligible: true, reasons: [] }} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
