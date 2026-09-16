import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttestorHubLayout } from "./attestor-hub-layout";

const nav = vi.hoisted(() => ({
  pathname: "/dashboard/organizations/org-1/attestor",
  replace: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ replace: nav.replace, push: nav.push }),
}));

// The layout reads role, capability, and counts from the org shell's context.
const org = vi.hoisted(() => ({
  role: "owner",
  capabilities: {} as Record<string, string>,
  counts: { offers: 0, queue: 0, invitations: 0 },
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", ...org }),
}));

const BASE = "/dashboard/organizations/org-1/attestor";

describe("AttestorHubLayout", () => {
  beforeEach(() => {
    nav.replace.mockReset();
    nav.push.mockReset();
    nav.pathname = BASE;
    org.role = "owner";
    org.capabilities = {};
    org.counts = { offers: 0, queue: 0, invitations: 0 };
  });

  it("shows the application alone, with no section nav, before the org is an attestor", () => {
    render(<AttestorHubLayout>application</AttestorHubLayout>);

    expect(screen.getByText("application")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: /attestor sections/i })).toBeNull();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("gives an admin of an active attestor Offers and Queue with counts", () => {
    org.capabilities = { attestor: "active" };
    org.counts = { offers: 2, queue: 3, invitations: 0 };
    nav.pathname = `${BASE}/queue`;

    render(<AttestorHubLayout>queue-page</AttestorHubLayout>);

    const sections = screen.getByRole("navigation", { name: /attestor sections/i });
    const buttons = Array.from(sections.querySelectorAll("button"));
    expect(buttons.map((button) => button.textContent)).toEqual(["Offers2", "Queue3"]);
    expect(buttons[1]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("queue-page")).toBeInTheDocument();

    fireEvent.click(buttons[0]);
    expect(nav.push).toHaveBeenCalledWith(`${BASE}/offers`);
  });

  it("opens the section that needs attention when the tab has no section", async () => {
    org.capabilities = { attestor: "active" };
    org.counts = { offers: 1, queue: 4, invitations: 0 };

    render(<AttestorHubLayout>application</AttestorHubLayout>);

    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`${BASE}/offers`));
    expect(screen.queryByText("application")).toBeNull();
  });

  it("leaves the application behind once the org is an attestor", async () => {
    org.capabilities = { attestor: "active" };
    nav.pathname = `${BASE}/application`;

    render(<AttestorHubLayout>application-page</AttestorHubLayout>);

    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`${BASE}/queue`));
    expect(screen.queryByText("application-page")).toBeNull();
  });

  it("sends a plain member to their queue and hides a one-section nav", async () => {
    org.role = "member";
    org.capabilities = { attestor: "active" };
    nav.pathname = `${BASE}/offers`;

    const { rerender } = render(<AttestorHubLayout>offers-page</AttestorHubLayout>);

    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`${BASE}/queue`));
    expect(screen.queryByText("offers-page")).toBeNull();

    nav.pathname = `${BASE}/queue`;
    rerender(<AttestorHubLayout>queue-page</AttestorHubLayout>);
    expect(screen.getByText("queue-page")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: /attestor sections/i })).toBeNull();
  });

  it("sends a section link back to the application before the org is an attestor", async () => {
    nav.pathname = `${BASE}/queue`;

    render(<AttestorHubLayout>queue-page</AttestorHubLayout>);

    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(BASE));
    expect(screen.queryByText("queue-page")).toBeNull();
  });
});
