import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EarningsSummary } from "@/components/modules/financials/earnings-summary";
import { getContributorEarnings } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getContributorEarnings: vi.fn(),
}));

describe("EarningsSummary", () => {
  beforeEach(() => {
    vi.mocked(getContributorEarnings).mockReset();
  });

  it("shows Contributor earnings and payout thresholds", async () => {
    vi.mocked(getContributorEarnings).mockResolvedValue({
      data: {
        available_balance: "637.50",
        commission_rate: "0.15",
        currency: "USD",
        gross_revenue: "1000.00",
        minimum_payout: "50.00",
        pending_clearance: "250.00",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<EarningsSummary />);

    expect(await screen.findByText("$637.50")).toBeInTheDocument();
    expect(screen.getByText("$1,000")).toBeInTheDocument();
    expect(screen.getByText("$250")).toBeInTheDocument();
    expect(screen.getByText("15% commission")).toBeInTheDocument();
    expect(screen.getByText("Minimum payout $50")).toBeInTheDocument();
  });
});
