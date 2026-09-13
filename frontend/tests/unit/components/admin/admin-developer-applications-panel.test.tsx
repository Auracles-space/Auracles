/**
 * Unit coverage for the admin developer-applications panel.
 *
 * Verifies the pending queue renders, the status filter refetches, and a
 * review (approve) submits and drops the application from the pending view.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminDeveloperApplicationsPanel } from "@/components/modules/admin/admin-developer-applications-panel";
import {
  listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet,
  reviewDeveloperApplicationV1AdminDeveloperApplicationsApplicationIdReviewPost,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet: vi.fn(),
  reviewDeveloperApplicationV1AdminDeveloperApplicationsApplicationIdReviewPost:
    vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://testserver"),
  response: new Response(null, { status: 200 }),
});

const pendingApp = {
  id: "app-1",
  user_id: "user-1",
  company_name: "Partner Systems Inc.",
  website: "https://partners.example.com",
  use_case: "Embed Auracles framework discovery into a CRM workflow.",
  status: "pending",
  admin_feedback: null,
  reviewed_by: null,
  reviewed_at: null,
  created_at: "2026-06-15T10:00:00Z",
};

describe("AdminDeveloperApplicationsPanel", () => {
  beforeEach(() => {
    vi.mocked(
      listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet,
    ).mockReset();
    vi.mocked(
      reviewDeveloperApplicationV1AdminDeveloperApplicationsApplicationIdReviewPost,
    ).mockReset();
    vi.mocked(
      listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet,
    ).mockResolvedValue(ok({ applications: [pendingApp] }));
  });

  it("renders the pending application queue", async () => {
    render(<AdminDeveloperApplicationsPanel />);

    expect(await screen.findByText("Partner Systems Inc.")).toBeInTheDocument();
    expect(
      screen.getByText(/Embed Auracles framework discovery/),
    ).toBeInTheDocument();
  });

  it("refetches when the status filter changes", async () => {
    render(<AdminDeveloperApplicationsPanel />);
    await screen.findByText("Partner Systems Inc.");

    vi.mocked(
      listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet,
    ).mockResolvedValue(
      ok({ applications: [{ ...pendingApp, id: "app-2", status: "approved", company_name: "Approved Co." }] }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^approved$/ }));

    expect(await screen.findByText("Approved Co.")).toBeInTheDocument();
  });

  it("approves an application and removes it from the queue", async () => {
    vi.mocked(
      reviewDeveloperApplicationV1AdminDeveloperApplicationsApplicationIdReviewPost,
    ).mockResolvedValue(ok({ ...pendingApp, status: "approved" }));

    render(<AdminDeveloperApplicationsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /^Review$/ }));

    fireEvent.click(screen.getByRole("button", { name: /^Approve$/ }));

    await waitFor(() =>
      expect(
        vi.mocked(
          reviewDeveloperApplicationV1AdminDeveloperApplicationsApplicationIdReviewPost,
        ),
      ).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(screen.queryByText("Partner Systems Inc.")).not.toBeInTheDocument(),
    );
  });

  it("offers review actions without asking for a code", async () => {
    // The API requires a step-up window; the global prompt handles a refusal.
    render(<AdminDeveloperApplicationsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /^Review$/ }));

    expect(screen.getByRole("button", { name: /^Approve$/ })).toBeEnabled();
    expect(screen.queryByLabelText(/authenticator code/i)).not.toBeInTheDocument();
  });
});
