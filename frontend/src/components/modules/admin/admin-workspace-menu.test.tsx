/**
 * Tests for the admin workspace menu on screens narrower than the sidebar.
 *
 * Below the sidebar breakpoint the admin navigation used to stack above every
 * page, pushing the page itself far down. It now sits behind a Menu button
 * that opens a drawer and closes again once the admin has chosen a page.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { adminListOrgsV1AdminOrgsGet, listAdminAttestations } from "@/lib/generated/sdk.gen";

import { AdminWorkspaceShell } from "./admin-workspace-shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/treasury",
}));

// jsdom cannot navigate; a plain anchor that stops the navigation keeps the
// click (and the drawer's close handler) without a noisy jsdom error.
vi.mock("next/link", () => ({
  default: ({
    children,
    onClick,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      {...props}
      onClick={(event) => {
        event.preventDefault();
        onClick?.(event);
      }}
    >
      {children}
    </a>
  ),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminListOrgsV1AdminOrgsGet: vi.fn(),
  listAdminAttestations: vi.fn(),
}));

function renderShell() {
  return render(
    <AdminWorkspaceShell>
      <div>Treasury page</div>
    </AdminWorkspaceShell>,
  );
}

describe("AdminWorkspaceShell menu on small screens", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [{ id: "att-1" }, { id: "att-2" }] },
    } as never);
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockResolvedValue({
      response: { ok: true },
      data: { orgs: [], page: 1, page_size: 1, total: 1 },
    } as never);
  });

  it("names the current page beside a closed Menu button", async () => {
    renderShell();

    const menu = screen.getByRole("button", { name: /Admin menu/i });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("admin-current-page")).toHaveTextContent("Treasury");
    expect(screen.queryByRole("dialog", { name: /Admin navigation/i })).toBeNull();
  });

  it("shows how many items need attention on the Menu button", async () => {
    renderShell();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Admin menu/i })).toHaveAccessibleName(
        "Admin menu, 3 items need attention",
      ),
    );
  });

  it("opens the navigation in a drawer and closes it when a page is chosen", async () => {
    renderShell();

    fireEvent.click(screen.getByRole("button", { name: /Admin menu/i }));
    const drawer = screen.getByRole("dialog", { name: /Admin navigation/i });
    expect(screen.getByRole("button", { name: /Admin menu/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    fireEvent.click(within(drawer).getByRole("link", { name: /Payouts/ }));

    expect(screen.queryByRole("dialog", { name: /Admin navigation/i })).toBeNull();
  });

  it("closes the drawer on Escape and from its close button", () => {
    renderShell();

    fireEvent.click(screen.getByRole("button", { name: /Admin menu/i }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /Admin navigation/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Admin menu/i }));
    fireEvent.click(screen.getByRole("button", { name: /Close menu/i }));
    expect(screen.queryByRole("dialog", { name: /Admin navigation/i })).toBeNull();
  });

  it("keeps the page beside the sidebar on wide screens", () => {
    // An empty drawer wrapper sat in the layout grid between the sidebar and
    // the page, pushing the page onto a second row under the sidebar.
    renderShell();

    const page = screen.getByText("Treasury page").parentElement;
    expect(page?.previousElementSibling?.tagName).toBe("ASIDE");
    const gridItems = Array.from(page?.parentElement?.children ?? []);
    const wideScreenItems = gridItems.filter(
      (item) => !item.className.includes("xl:hidden"),
    );
    expect(wideScreenItems).toHaveLength(2);
  });
});
