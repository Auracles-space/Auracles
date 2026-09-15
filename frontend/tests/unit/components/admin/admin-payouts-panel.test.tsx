/**
 * Admin payouts panel — beneficiaries are named, organizations are linked,
 * and the directory can be narrowed to one organization.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPayoutsPanel } from "@/components/modules/admin/admin-payouts-panel";
import { listAdminPayoutsV1AdminPayoutsGet } from "@/lib/generated/sdk.gen";
import { formatMoney } from "@/lib/marketplace/format";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ listAdminPayoutsV1AdminPayoutsGet: vi.fn() }));

const ORG_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function payout(overrides: Record<string, unknown>) {
  return {
    payout_id: crypto.randomUUID(),
    amount: "50000.00",
    net_amount: "45000.00",
    commission_deducted: "5000.00",
    currency: "NGN",
    provider: "paystack",
    provider_ref: null,
    status: "completed",
    initiated_at: "2026-09-01T09:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function respond(items: unknown[]) {
  vi.mocked(listAdminPayoutsV1AdminPayoutsGet).mockResolvedValue({
    data: { items, page: 1, page_size: 20, total: items.length },
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

describe("AdminPayoutsPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("refetches when the admin returns to the tab so a settled payout is not stale", async () => {
    // A payout completed by a provider webhook kept showing Processing until a
    // manual reload, because the list only loaded on mount and filter changes.
    respond([payout({ status: "processing", beneficiary_type: "org", beneficiary_id: ORG_ID, beneficiary_name: "Ikeji Advisory" })]);
    render(<AdminPayoutsPanel />);
    await screen.findByText("Ikeji Advisory");
    expect(listAdminPayoutsV1AdminPayoutsGet).toHaveBeenCalledTimes(1);

    respond([payout({ status: "completed", beneficiary_type: "org", beneficiary_id: ORG_ID, beneficiary_name: "Ikeji Advisory" })]);
    fireEvent(window, new Event("focus"));

    await waitFor(() => expect(listAdminPayoutsV1AdminPayoutsGet).toHaveBeenCalledTimes(2));
  });

  it("names an organization beneficiary and links it to the org detail page", async () => {
    respond([
      payout({ beneficiary_type: "org", beneficiary_id: ORG_ID, beneficiary_name: "Meridian Audit" }),
    ]);
    render(<AdminPayoutsPanel />);

    const link = await screen.findByRole("link", { name: "Meridian Audit" });
    expect(link).toHaveAttribute("href", `/admin/organizations/${ORG_ID}`);
    expect(link.className).toMatch(/min-h-11/);
  });

  it("names a contributor beneficiary without linking it", async () => {
    respond([
      payout({ beneficiary_type: "contributor", beneficiary_id: "bbbbbbbb-1111", beneficiary_name: "Ada Okafor" }),
    ]);
    render(<AdminPayoutsPanel />);

    expect(await screen.findByText("Ada Okafor")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("falls back to a short id when the beneficiary has no name", async () => {
    respond([payout({ beneficiary_type: "org", beneficiary_id: ORG_ID, beneficiary_name: null })]);
    render(<AdminPayoutsPanel />);

    const link = await screen.findByRole("link", { name: /aaaaaaaa/ });
    expect(link).toHaveAttribute("href", `/admin/organizations/${ORG_ID}`);
    expect(link).not.toHaveTextContent(ORG_ID);
  });

  it("passes a valid organization ID filter as org_id and clears it", async () => {
    respond([]);
    render(<AdminPayoutsPanel />);
    const input = await screen.findByLabelText("Organization ID");

    fireEvent.change(input, { target: { value: "not-a-uuid" } });
    expect(listAdminPayoutsV1AdminPayoutsGet).not.toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ org_id: "not-a-uuid" }) }),
    );

    fireEvent.change(screen.getByLabelText("Organization ID"), { target: { value: ORG_ID } });
    await waitFor(() =>
      expect(listAdminPayoutsV1AdminPayoutsGet).toHaveBeenLastCalledWith(
        expect.objectContaining({
          query: expect.objectContaining({ org_id: ORG_ID, status: "all", provider: "all" }),
        }),
      ),
    );

    const clear = screen.getByRole("button", { name: "Clear organization filter" });
    expect(clear.className).toMatch(/min-h-11/);
    fireEvent.click(clear);
    await waitFor(() =>
      expect(listAdminPayoutsV1AdminPayoutsGet).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: expect.not.objectContaining({ org_id: ORG_ID }) }),
      ),
    );
    expect(screen.getByLabelText("Organization ID")).toHaveValue("");
  });

  /** NGN and USD rows in one list each render in their own currency (NGN is the primary rail). */
  it("formats each row in its own currency with the shared formatMoney", async () => {
    respond([
      payout({ beneficiary_type: "contributor", beneficiary_id: "cccccccc-1111", beneficiary_name: "Ngozi Eze" }),
      payout({
        beneficiary_type: "contributor",
        beneficiary_id: "dddddddd-2222",
        beneficiary_name: "Sam Carter",
        amount: "120.50",
        net_amount: "108.45",
        currency: "USD",
        provider: "stripe",
      }),
    ]);
    render(<AdminPayoutsPanel />);
    await screen.findByText("Ngozi Eze");

    const nairaNet = formatMoney("45000.00", "NGN");
    expect(nairaNet).toContain("\u20a6");
    expect(screen.getByText(nairaNet)).toBeInTheDocument();
    expect(screen.getByText(`gross ${formatMoney("50000.00", "NGN")}`)).toBeInTheDocument();

    expect(screen.getByText(formatMoney("108.45", "USD"))).toHaveTextContent("$108.45");
    expect(screen.getByText(`gross ${formatMoney("120.50", "USD")}`)).toBeInTheDocument();
  });
});
