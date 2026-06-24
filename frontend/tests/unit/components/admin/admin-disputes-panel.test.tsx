/**
 * Unit coverage for the admin project-dispute panel.
 *
 * Verifies the active queue renders dispute money context, the status filter
 * refetches resolved disputes, and a release resolution submits and clears the
 * dispute from the active queue.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminDisputesPanel } from "@/components/modules/admin/admin-disputes-panel";
import {
  listAdminProjectDisputes,
  resolveAdminProjectDispute,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminProjectDisputes: vi.fn(),
  resolveAdminProjectDispute: vi.fn(),
}));

vi.mock("@/components/modules/auth/totp-input", () => ({
  TotpInput: ({
    onChange,
    value,
  }: {
    onChange: (value: string) => void;
    value: string;
  }) => (
    <input
      aria-label="totp"
      onChange={(event) => onChange(event.target.value)}
      value={value}
    />
  ),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://testserver"),
  response: new Response(null, { status: 200 }),
});

const activeDispute = {
  id: "dispute-1",
  project_id: "project-1",
  milestone_id: "milestone-1",
  raised_by: "operator-1",
  reason: "Deliverable did not meet the agreed scope.",
  status: "open",
  resolution_type: null,
  release_amount: null,
  refund_amount: null,
  admin_id: null,
  resolution_notes: null,
  escalated_at: null,
  resolved_at: null,
  created_at: "2026-06-18T09:00:00Z",
  project_title: "Risk Operating Model Build",
  milestone_name: "Phase 1 Discovery",
  milestone_budget: "1500.00",
  currency: "USD",
  escrow_amount: "1500.00",
  escrow_status: "held",
  raised_by_name: "Olu Operator",
  raised_by_role: "operator",
  operator_name: "Olu Operator",
  contributor_name: "Ada Contributor",
};

const resolvedDispute = {
  ...activeDispute,
  id: "dispute-2",
  status: "resolved",
  resolution_type: "release",
  resolved_at: "2026-06-19T09:00:00Z",
  resolution_notes: "Released to contributor after review.",
  project_title: "Resolved Engagement",
};

describe("AdminDisputesPanel", () => {
  beforeEach(() => {
    vi.mocked(listAdminProjectDisputes).mockReset();
    vi.mocked(resolveAdminProjectDispute).mockReset();
    vi.mocked(listAdminProjectDisputes).mockResolvedValue(
      ok({ disputes: [activeDispute] }),
    );
  });

  it("renders active disputes with their money and party context", async () => {
    render(<AdminDisputesPanel />);

    expect(
      await screen.findByText("Risk Operating Model Build"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Ada Contributor/)).toBeInTheDocument();
    expect(screen.getAllByText(/Olu Operator/).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Deliverable did not meet the agreed scope\./),
    ).toBeInTheDocument();
  });

  it("refetches resolved disputes when the filter changes", async () => {
    render(<AdminDisputesPanel />);
    await screen.findByText("Risk Operating Model Build");

    vi.mocked(listAdminProjectDisputes).mockResolvedValue(
      ok({ disputes: [resolvedDispute] }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Resolved$/ }));

    expect(await screen.findByText("Resolved Engagement")).toBeInTheDocument();
    await waitFor(() =>
      expect(vi.mocked(listAdminProjectDisputes)).toHaveBeenCalledTimes(2),
    );
  });

  it("submits a release resolution and drops the dispute from the queue", async () => {
    vi.mocked(resolveAdminProjectDispute).mockResolvedValue(
      ok({ ...activeDispute, status: "resolved", resolution_type: "release" }),
    );

    render(<AdminDisputesPanel />);
    fireEvent.click(
      await screen.findByRole("button", { name: /resolve dispute/i }),
    );

    fireEvent.change(screen.getByPlaceholderText(/audit log details/i), {
      target: { value: "Contributor delivered after mediation." },
    });
    fireEvent.change(screen.getByLabelText("totp"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm resolution/i }));

    await waitFor(() =>
      expect(vi.mocked(resolveAdminProjectDispute)).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Risk Operating Model Build"),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps the confirm button disabled until notes and a code are entered", async () => {
    render(<AdminDisputesPanel />);
    fireEvent.click(
      await screen.findByRole("button", { name: /resolve dispute/i }),
    );

    expect(
      screen.getByRole("button", { name: /confirm resolution/i }),
    ).toBeDisabled();
  });
});
