import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { vi } from "vitest";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

let mockPathname = "/explore";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/components/modules/layout/authenticated-account-menu", () => ({
  AuthenticatedAccountMenu: () => <div>Account menu</div>,
}));

vi.mock("@/components/modules/layout/notification-dropdown", () => ({
  NotificationDropdown: () => <div>Notifications dropdown</div>,
}));

vi.mock("@/components/modules/settings/pending-invitations-toast", () => ({
  PendingInvitationsToast: () => null,
}));

// The shell bootstraps the session on mount (BrowserSessionGate +
// AttestorApplicationPrompt). Stub it so the render never makes a real
// /auth/refresh fetch — otherwise the request escapes to localhost:8000 and
// surfaces as an unhandled rejection that can mask real failures.
vi.mock("@/lib/auth/current-user-session", () => ({
  clearBrowserSessionHintCookie: vi.fn(),
  ensureBrowserAccessToken: vi.fn(async () => true),
  loadCurrentUserSession: vi.fn(async () => null),
}));

describe("AuthenticatedAppShell", () => {
  it("renders persistent product navigation around app pages", () => {
    mockPathname = "/explore";
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
    expect(within(appNav).getByRole("link", { name: /projects/i })).toHaveAttribute(
      "href",
      "/projects",
    );
    expect(within(appNav).getByRole("link", { name: /settings/i })).toHaveAttribute(
      "href",
      "/settings/identity",
    );
  });

  it("hides admin navigation for non-admin roles", () => {
    mockPathname = "/library";
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

  it("highlights the Explore link when on the explore catalog or detail pages", () => {
    mockPathname = "/explore/00000000-0000-4000-8000-000000000013";
    render(
      <AuthenticatedAppShell roles={["operator"]}>
        <h1>Framework</h1>
      </AuthenticatedAppShell>,
    );

    const appNav = screen.getByRole("navigation", {
      name: /^application navigation$/i,
    });

    const exploreLink = within(appNav).getByRole("link", { name: /^explore$/i });
    expect(exploreLink.className).toContain("bg-surface-1");
  });

  it("highlights the Library link and not Explore when on library", () => {
    mockPathname = "/library";
    render(
      <AuthenticatedAppShell roles={["operator"]}>
        <h1>Library</h1>
      </AuthenticatedAppShell>,
    );

    const appNav = screen.getByRole("navigation", {
      name: /^application navigation$/i,
    });

    const exploreLink = within(appNav).getByRole("link", { name: /^explore$/i });
    const libraryLink = within(appNav).getByRole("link", { name: /^library$/i });

    expect(libraryLink.className).toContain("bg-surface-1");
    expect(exploreLink.className).not.toContain("bg-surface-1");
  });
});
