/**
 * Unit coverage for the admin workspace shell.
 *
 * Verifies that authenticated admin routes get a dedicated local navigation
 * model inside the shared application shell.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AdminWorkspaceShell } from "@/components/modules/admin/admin-workspace-shell";

describe("AdminWorkspaceShell", () => {
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
});
