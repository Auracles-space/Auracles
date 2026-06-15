import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { vi } from "vitest";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

vi.mock("@/components/modules/layout/authenticated-account-menu", () => ({
  AuthenticatedAccountMenu: () => <div>Account menu</div>,
}));

describe("AuthenticatedAppShell", () => {
  it("renders persistent product navigation around app pages", () => {
    render(
      <AuthenticatedAppShell roles={["operator", "contributor"]}>
        <h1>Frameworks</h1>
      </AuthenticatedAppShell>,
    );

    expect(screen.getAllByRole("link", { name: /^auracles$/i })[0]).toHaveAttribute(
      "href",
      "/explore",
    );

    const appNav = screen.getByRole("navigation", {
      name: /^application navigation$/i,
    });

    expect(within(appNav).getByRole("link", { name: /frameworks/i })).toHaveAttribute(
      "href",
      "/dashboard/frameworks",
    );
    expect(within(appNav).getByRole("link", { name: /library/i })).toHaveAttribute(
      "href",
      "/library",
    );
    expect(
      within(appNav).getByRole("link", { name: /notifications/i }),
    ).toHaveAttribute("href", "/settings/notifications");
    expect(within(appNav).getByRole("link", { name: /projects/i })).toHaveAttribute(
      "href",
      "/projects",
    );
    expect(within(appNav).getByRole("link", { name: /settings/i })).toHaveAttribute(
      "href",
      "/settings/profile",
    );
  });

  it("hides admin navigation for non-admin roles", () => {
    render(
      <AuthenticatedAppShell roles={["operator"]}>
        <h1>Library</h1>
      </AuthenticatedAppShell>,
    );

    const appNav = screen.getByRole("navigation", {
      name: /^application navigation$/i,
    });

    expect(
      within(appNav).queryByRole("link", { name: /^admin$/i }),
    ).not.toBeInTheDocument();
  });
});
