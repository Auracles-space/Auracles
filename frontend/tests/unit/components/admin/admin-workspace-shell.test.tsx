/**
 * Unit coverage for the admin workspace shell.
 *
 * Verifies that authenticated admin routes get a dedicated local navigation
 * model inside the shared application shell.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminWorkspaceShell } from "@/components/modules/admin/admin-workspace-shell";
import { listAdminAttestations } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminAttestations: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer access-token" })),
}));

const listAttestations = vi.mocked(listAdminAttestations);

describe("AdminWorkspaceShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listAttestations.mockResolvedValue({
      data: { attestations: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
  });

  it("renders focused admin navigation around nested admin pages", () => {
    render(
      <AdminWorkspaceShell>
        <h1>Analytics</h1>
      </AdminWorkspaceShell>,
    );

    const adminNav = screen.getByRole("navigation", { name: /admin navigation/i });

    expect(within(adminNav).getByRole("link", { name: /analytics/i })).toHaveAttribute(
      "href",
      "/admin/analytics",
    );
    expect(
      within(adminNav).getByRole("link", { name: /moderation/i }),
    ).toHaveAttribute("href", "/admin/moderation");
    expect(within(adminNav).getByRole("link", { name: /users/i })).toHaveAttribute(
      "href",
      "/admin/users",
    );
    expect(
      within(adminNav).getByRole("link", { name: /attestations/i }),
    ).toHaveAttribute("href", "/admin/attestations");
    expect(screen.getByRole("heading", { name: "Analytics" })).toBeInTheDocument();
  });

  it("still renders the navigation when the needs-admin count cannot load", async () => {
    // The count is a badge on one nav item. A failed request must not reject
    // into the void — the shell wraps every admin page, so an uncaught
    // rejection here is an error on screens that have nothing to do with it.
    const unhandled = vi.fn();
    process.on("unhandledRejection", unhandled);
    listAttestations.mockRejectedValue(new Error("network down"));

    render(
      <AdminWorkspaceShell>
        <h1>Analytics</h1>
      </AdminWorkspaceShell>,
    );

    await waitFor(() => {
      expect(listAttestations).toHaveBeenCalled();
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    process.off("unhandledRejection", unhandled);

    expect(
      screen.getByRole("navigation", { name: /admin navigation/i }),
    ).toBeInTheDocument();
    expect(unhandled).not.toHaveBeenCalled();
  });
});
