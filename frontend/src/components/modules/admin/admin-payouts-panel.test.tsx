/**
 * Tests for the admin payouts oversight panel.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPayoutsPanel } from "@/components/modules/admin/admin-payouts-panel";
import { listAdminPayoutsV1AdminPayoutsGet as listPayouts } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "Request failed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminPayoutsV1AdminPayoutsGet: vi.fn(),
}));

function payout(overrides: Record<string, unknown>) {
  return {
    payout_id: crypto.randomUUID(),
    beneficiary_type: "contributor",
    beneficiary_id: "user-1",
    beneficiary_name: "Ada Obi",
    provider: "paystack",
    amount: "85000.00",
    commission_deducted: "0.00",
    net_amount: "85000.00",
    currency: "NGN",
    status: "processing",
    provider_ref: "payout-1",
    initiated_at: "2026-09-16T12:00:00Z",
    completed_at: null,
    awaiting_otp: false,
    ...overrides,
  };
}

describe("AdminPayoutsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names a payout Paystack is holding for an OTP", async () => {
    vi.mocked(listPayouts).mockResolvedValue({
      data: {
        items: [
          payout({ awaiting_otp: true, beneficiary_name: "Ada Obi" }),
          payout({ awaiting_otp: false, beneficiary_name: "Ikeji Advisory" }),
        ],
        total: 2,
        page: 1,
        page_size: 20,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<AdminPayoutsPanel />);

    expect(await screen.findByText("Waiting for OTP")).toBeInTheDocument();
    expect(screen.getAllByText("processing")).toHaveLength(1);
  });
});
