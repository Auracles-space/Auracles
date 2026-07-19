/**
 * Milestone funding return-route tests.
 *
 * Ensures Stripe returns an organization payer to the organization-scoped
 * workspace instead of dropping it into the personal Project route.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MilestoneFundingPanel } from "@/components/modules/projects/milestone-funding-panel";

const confirmPayment = vi.fn().mockResolvedValue({ error: undefined });

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve({})),
}));

vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PaymentElement: () => <div>Payment fields</div>,
  useElements: () => ({}),
  useStripe: () => ({ confirmPayment }),
}));

describe("MilestoneFundingPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("returns organization funding to the organization Project workspace", async () => {
    render(
      <MilestoneFundingPanel
        clientSecret="secret"
        milestoneId="milestone-1"
        onCancel={vi.fn()}
        projectId="project-1"
        returnPath="/dashboard/organizations/org-1/projects/project-1"
        transactionId="transaction-1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /pay and fund milestone/i }));

    await waitFor(() => expect(confirmPayment).toHaveBeenCalledTimes(1));
    expect(confirmPayment.mock.calls[0][0].confirmParams.return_url).toContain(
      "/dashboard/organizations/org-1/projects/project-1?funded=transaction-1&funded_milestone=milestone-1",
    );
  });
});
