import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MembersSectionsLayout } from "./members-sections-layout";

const nav = vi.hoisted(() => ({
  pathname: "/dashboard/organizations/org-1/members",
  replace: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ replace: nav.replace, push: nav.push }),
}));

const org = vi.hoisted(() => ({ role: "owner", counts: { offers: 0, queue: 0, invitations: 0 } }));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", ...org }),
}));

const BASE = "/dashboard/organizations/org-1/members";

describe("MembersSectionsLayout", () => {
  beforeEach(() => {
    nav.replace.mockReset();
    nav.push.mockReset();
    nav.pathname = BASE;
    org.role = "owner";
    org.counts = { offers: 0, queue: 0, invitations: 0 };
  });

  it("gives an admin Members, Invitations, and Teams with the pending invitation count", () => {
    org.counts = { offers: 0, queue: 0, invitations: 2 };
    nav.pathname = `${BASE}/invitations`;

    render(<MembersSectionsLayout>invitations-page</MembersSectionsLayout>);

    const sections = screen.getByRole("navigation", { name: /member sections/i });
    const buttons = Array.from(sections.querySelectorAll("button"));
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Members",
      "Invitations2",
      "Teams",
    ]);
    expect(buttons[1]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("invitations-page")).toBeInTheDocument();

    fireEvent.click(buttons[2]);
    expect(nav.push).toHaveBeenCalledWith(`${BASE}/teams`);
    fireEvent.click(buttons[0]);
    expect(nav.push).toHaveBeenCalledWith(BASE);
  });

  it("shows a plain member the list with no section control", () => {
    org.role = "member";

    render(<MembersSectionsLayout>members-page</MembersSectionsLayout>);

    expect(screen.getByText("members-page")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: /member sections/i })).toBeNull();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("sends a plain member away from the admin-only sections", async () => {
    org.role = "member";
    nav.pathname = `${BASE}/teams`;

    render(<MembersSectionsLayout>teams-page</MembersSectionsLayout>);

    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(BASE));
    expect(screen.queryByText("teams-page")).toBeNull();
  });
});
