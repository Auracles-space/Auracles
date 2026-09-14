/**
 * Admin payouts panel — beneficiaries are named, organizations are linked,
 * and the directory can be narrowed to one organization.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPayoutsPanel } from "@/components/modules/admin/admin-payouts-panel";
import { listAdminPayoutsV1AdminPayoutsGet } from "@/lib/generated/sdk.gen";

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
});
