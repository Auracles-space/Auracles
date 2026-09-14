/**
 * Organization payout history tests.
 *
 * Owners track requested payouts here: amounts in the payout's own currency,
 * canonical status pills, dates, failure reasons, and paging past the first
 * page (spec 2026-09-14 §Slice C).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listOrgPayoutsV1OrgsOrgIdFinancialsPayoutsGet as listOrgPayouts } from "@/lib/generated/sdk.gen";
import { formatMoney } from "@/lib/marketplace/format";

import { OrgPayoutHistory } from "./org-payout-history";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgPayoutsV1OrgsOrgIdFinancialsPayoutsGet: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/form-client")>()),
  configureBrowserClient: vi.fn(),
}));

const paid = {
  id: "po-1",
  amount: "98000.00",
  currency: "NGN",
  status: "completed",
  provider: "paystack",
  requested_at: "2026-09-01T10:00:00Z",
  completed_at: "2026-09-03T10:00:00Z",
  failure_reason: null,
};

const failed = {
  id: "po-2",
  amount: "15000.50",
  currency: "NGN",
  status: "failed",
  provider: "paystack",
  requested_at: "2026-08-20T10:00:00Z",
  completed_at: null,
  failure_reason: "Bank account could not be credited.",
};

describe("OrgPayoutHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows each payout with amount, status, dates, and failure reason", async () => {
    vi.mocked(listOrgPayouts).mockResolvedValue({
      data: { payouts: [paid, failed], page: 1, page_size: 20, total: 2 },
      response: { ok: true, status: 200 },
    } as never);

    render(<OrgPayoutHistory orgId="org-1" />);

    expect(await screen.findByText(formatMoney("98000.00", "NGN"))).toBeInTheDocument();
    expect(screen.getByText(formatMoney("15000.50", "NGN"))).toBeInTheDocument();
    expect(screen.getByText("Paid").className).toContain("rounded-badge");
    expect(screen.getByText("Failed").className).toContain("text-error");
    expect(screen.getByText("Requested 1 Sep 2026")).toBeInTheDocument();
    expect(screen.getByText("Paid 3 Sep 2026")).toBeInTheDocument();
    expect(screen.getByText("Bank account could not be credited.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    expect(listOrgPayouts).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1" },
        query: expect.objectContaining({ page: 1 }),
      }),
    );
  });

  it("shows an empty state when the org has never requested a payout", async () => {
    vi.mocked(listOrgPayouts).mockResolvedValue({
      data: { payouts: [], page: 1, page_size: 20, total: 0 },
      response: { ok: true, status: 200 },
    } as never);

    render(<OrgPayoutHistory orgId="org-1" />);

    expect(await screen.findByText("No payouts yet.")).toBeInTheDocument();
  });

  it("describes a load failure", async () => {
    vi.mocked(listOrgPayouts).mockResolvedValue({
      data: undefined,
      error: { detail: "Only owners can view payouts." },
      response: { ok: false, status: 403 },
    } as never);

    render(<OrgPayoutHistory orgId="org-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only owners can view payouts.",
    );
  });

  it("loads the next page when there are more payouts than one page", async () => {
    vi.mocked(listOrgPayouts)
      .mockResolvedValueOnce({
        data: { payouts: [paid], page: 1, page_size: 1, total: 2 },
        response: { ok: true, status: 200 },
      } as never)
      .mockResolvedValueOnce({
        data: { payouts: [failed], page: 2, page_size: 1, total: 2 },
        response: { ok: true, status: 200 },
      } as never);

    render(<OrgPayoutHistory orgId="org-1" />);

    const more = await screen.findByRole("button", { name: "Load more" });
    fireEvent.click(more);

    expect(await screen.findByText(formatMoney("15000.50", "NGN"))).toBeInTheDocument();
    expect(screen.getByText(formatMoney("98000.00", "NGN"))).toBeInTheDocument();
    expect(listOrgPayouts).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ page: 2 }) }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Load more" })).toBeNull(),
    );
  });
});
