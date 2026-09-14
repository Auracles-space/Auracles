/**
 * Organization failed-payments section tests.
 *
 * A failed Framework purchase must be visible in billing with the reason, so
 * an admin can fix the card or bank issue and retry (spec 2026-09-14 §Slice C).
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listOrgPurchasesV1OrgsOrgIdFinancialsPurchasesGet as listOrgPurchases } from "@/lib/generated/sdk.gen";
import { formatMoney } from "@/lib/marketplace/format";

import { OrgFailedPayments } from "./org-failed-payments";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgPurchasesV1OrgsOrgIdFinancialsPurchasesGet: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/form-client")>()),
  configureBrowserClient: vi.fn(),
}));

describe("OrgFailedPayments", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists failed purchases with title, amount, date, and reason", async () => {
    vi.mocked(listOrgPurchases).mockResolvedValue({
      data: {
        purchases: [
          {
            transaction_id: "txn-1",
            framework_id: "fw-1",
            framework_title: "Board Risk Operating System",
            amount: "45000.00",
            currency: "NGN",
            status: "failed",
            failure_reason: "Insufficient funds.",
            created_at: "2026-09-02T09:00:00Z",
          },
        ],
      },
      response: { ok: true, status: 200 },
    } as never);

    render(<OrgFailedPayments orgId="org-1" />);

    expect(
      await screen.findByRole("heading", { name: "Failed payments" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Board Risk Operating System")).toBeInTheDocument();
    expect(screen.getByText(formatMoney("45000.00", "NGN"))).toBeInTheDocument();
    expect(screen.getByText("2 Sep 2026")).toBeInTheDocument();
    expect(screen.getByText("Insufficient funds.")).toBeInTheDocument();
    expect(listOrgPurchases).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1" },
        query: expect.objectContaining({ status: "failed" }),
      }),
    );
  });

  it("renders nothing when no purchase has failed", async () => {
    vi.mocked(listOrgPurchases).mockResolvedValue({
      data: { purchases: [] },
      response: { ok: true, status: 200 },
    } as never);

    const { container } = render(<OrgFailedPayments orgId="org-1" />);

    await waitFor(() => expect(listOrgPurchases).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("describes a load failure", async () => {
    vi.mocked(listOrgPurchases).mockResolvedValue({
      data: undefined,
      error: { detail: "Purchases are unavailable." },
      response: { ok: false, status: 500 },
    } as never);

    render(<OrgFailedPayments orgId="org-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Purchases are unavailable.",
    );
  });
});
