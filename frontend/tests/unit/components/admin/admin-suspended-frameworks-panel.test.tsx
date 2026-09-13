/**
 * Unit coverage for the admin suspended-frameworks panel.
 *
 * Verifies the takedown list renders, an empty state shows when nothing is
 * suspended, and reinstating a Framework removes it from the list.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminSuspendedFrameworksPanel } from "@/components/modules/admin/admin-suspended-frameworks-panel";
import {
  listSuspendedFrameworksV1AdminFrameworksSuspendedGet,
  reinstateFrameworkV1AdminFrameworksFrameworkIdReinstatePost,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listSuspendedFrameworksV1AdminFrameworksSuspendedGet: vi.fn(),
  reinstateFrameworkV1AdminFrameworksFrameworkIdReinstatePost: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://testserver"),
  response: new Response(null, { status: 200 }),
});

const suspendedItem = {
  framework_id: "framework-1",
  title: "Governance Operating Model",
  contributor_id: "contributor-1",
  contributor_name: "Ada Contributor",
  reason: "Post-publish moderation hit.",
  suspended_at: "2026-06-20T10:00:00Z",
};

describe("AdminSuspendedFrameworksPanel", () => {
  beforeEach(() => {
    vi.mocked(listSuspendedFrameworksV1AdminFrameworksSuspendedGet).mockReset();
    vi.mocked(reinstateFrameworkV1AdminFrameworksFrameworkIdReinstatePost).mockReset();
    vi.mocked(listSuspendedFrameworksV1AdminFrameworksSuspendedGet).mockResolvedValue(
      ok({ items: [suspendedItem] }),
    );
  });

  it("lists suspended frameworks with their takedown reason", async () => {
    render(<AdminSuspendedFrameworksPanel />);

    expect(
      await screen.findByText("Governance Operating Model"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Ada Contributor/)).toBeInTheDocument();
    expect(screen.getByText(/Post-publish moderation hit\./)).toBeInTheDocument();
  });

  it("removes a framework from the list after reinstating it", async () => {
    vi.mocked(
      reinstateFrameworkV1AdminFrameworksFrameworkIdReinstatePost,
    ).mockResolvedValue(
      ok({ framework_id: "framework-1", status: "published", reason: null }),
    );

    render(<AdminSuspendedFrameworksPanel />);
    const reinstate = await screen.findByRole("button", { name: /reinstate/i });
    // Reinstatement is step-up gated server-side; the global prompt handles a
    // refusal, so the panel collects no code.
    expect(screen.queryByLabelText(/authenticator code/i)).not.toBeInTheDocument();

    fireEvent.click(reinstate);

    await waitFor(() =>
      expect(
        screen.queryByText("Governance Operating Model"),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(/no frameworks are currently suspended/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error when reinstatement fails", async () => {
    vi.mocked(
      reinstateFrameworkV1AdminFrameworksFrameworkIdReinstatePost,
    ).mockResolvedValue({
      data: undefined,
      error: { detail: "boom" },
      request: new Request("http://testserver"),
      response: new Response(null, { status: 409 }),
    });

    render(<AdminSuspendedFrameworksPanel />);
    await screen.findByRole("button", { name: /reinstate/i });
    fireEvent.click(screen.getByRole("button", { name: /reinstate/i }));

    expect(
      await screen.findByText("The request could not be completed."),
    ).toBeInTheDocument();
    // The framework stays in the list when reinstatement is refused.
    expect(screen.getByText("Governance Operating Model")).toBeInTheDocument();
  });

  it("shows the empty state when nothing is suspended", async () => {
    vi.mocked(listSuspendedFrameworksV1AdminFrameworksSuspendedGet).mockResolvedValue(
      ok({ items: [] }),
    );

    render(<AdminSuspendedFrameworksPanel />);

    expect(
      await screen.findByText(/no frameworks are currently suspended/i),
    ).toBeInTheDocument();
  });
});
