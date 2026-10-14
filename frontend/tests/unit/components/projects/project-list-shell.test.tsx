import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectListShell } from "@/components/modules/projects/project-list-shell";

const { push, replace, tokenRoles } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  tokenRoles: { current: [] as string[] },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/projects",
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "Error",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test-token" }),
}));

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: {
    // Mutable so a case can act as a specific role; reset to [] each test.
    getState: () => ({ roles: tokenRoles.current }),
  },
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  deleteOrgProject: vi.fn(),
  listProjects: vi.fn(),
  listOrgProjects: vi.fn(),
}));

describe("ProjectListShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tokenRoles.current = [];
  });

  it("sends a Contributor to the role page instead of a form they cannot submit", async () => {
    // Posting is Operator-gated, but the route guard admits Contributors, so an
    // unconditional CTA let them fill in the whole form and lose it to a 403.
    tokenRoles.current = ["contributor"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<ProjectListShell mode={{ kind: "self" }} />);

    const cta = await screen.findByRole("link", { name: /become an operator/i });
    expect(cta).toHaveAttribute("href", "/settings/roles?next=%2Fprojects%2Fnew");
    expect(
      screen.queryByRole("link", { name: /^post project$/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the direct post link for an Operator", async () => {
    tokenRoles.current = ["operator"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<ProjectListShell mode={{ kind: "self" }} />);

    expect(
      await screen.findByRole("link", { name: /^post project$/i }),
    ).toHaveAttribute("href", "/projects/new");
  });

  it("calls listOrgProjects when mode is org", async () => {
    const { listOrgProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listOrgProjects).mockResolvedValue({
      data: { projects: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<ProjectListShell mode={{ kind: "org", orgId: "org-1" }} />);

    await waitFor(() => {
      expect(listOrgProjects).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1" } })
      );
    });
  });

  it("keeps org project navigation inside the organization dashboard", async () => {
    const { listOrgProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listOrgProjects).mockResolvedValue({
      data: {
        projects: [
          {
            id: "proj-1",
            title: "Controls rollout",
            description: "Deploy the control framework.",
            status: "open",
            budget_min: "1000.00",
            budget_max: "2000.00",
            category: "governance",
            milestone_plan_status: "draft",
          },
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<ProjectListShell mode={{ kind: "org", orgId: "org-1" }} />);

    expect(await screen.findByRole("link", { name: /^controls rollout/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/projects/proj-1",
    );
    expect(screen.getByRole("link", { name: /post project/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/projects?view=create",
    );
    // Reaching the edit form only from inside the workspace hid it behind a
    // navigation nobody had a reason to make, so the card offers it too.
    expect(
      screen.getByRole("link", { name: /edit controls rollout/i }),
    ).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/projects/proj-1/edit",
    );
  });

  it("confirms org project deletion from the card and removes it", async () => {
    const { deleteOrgProject, listOrgProjects } = await import(
      "@/lib/generated/sdk.gen"
    );
    vi.mocked(listOrgProjects).mockResolvedValue({
      data: {
        projects: [
          {
            id: "proj-1",
            title: "Controls rollout",
            description: "Deploy the control framework.",
            status: "open",
            budget_min: "1000.00",
            budget_max: "2000.00",
            category: "governance",
            milestone_plan_status: "draft",
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    vi.mocked(deleteOrgProject).mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    } as never);
    render(<ProjectListShell mode={{ kind: "org", orgId: "org-1" }} />);

    fireEvent.click(
      await screen.findByRole("button", { name: /delete controls rollout/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^delete project$/i }));

    await waitFor(() => expect(deleteOrgProject).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByRole("link", { name: /controls rollout/i }),
    ).not.toBeInTheDocument();
    // The count has to follow the row out, or the pager keeps describing a
    // Project that is no longer there.
    expect(
      screen.queryByRole("navigation", { name: /project list pages/i }),
    ).not.toBeInTheDocument();
  });

  it("prices a Project in the currency it was posted in", async () => {
    // The card hardcoded a "$" prefix and ignored project.currency, so every
    // naira budget on an NGN deployment read as dollars.
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: {
        projects: [
          {
            id: "proj-1",
            title: "Controls rollout",
            description: "Deploy the control framework.",
            status: "open",
            budget_min: "1000.00",
            budget_max: "2000.00",
            currency: "NGN",
            category: "governance",
            milestone_plan_status: "draft",
          },
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<ProjectListShell mode={{ kind: "self" }} />);

    const budget = await screen.findByText(/1,000/);
    expect(budget).toHaveTextContent("₦1,000 – ₦2,000");
    expect(budget.textContent).not.toContain("$");
  });

  it("pages through a list longer than one response", async () => {
    // The shell asked for no page at all, so it took the backend default of 20
    // and rendered exactly one page with no way to reach the rest.
    tokenRoles.current = ["operator"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    const page = (start: number) => ({
      data: {
        projects: [
          {
            id: `proj-${start}`,
            title: `Project ${start}`,
            description: "Deploy the control framework.",
            status: "open",
            budget_min: "1000.00",
            budget_max: "2000.00",
            currency: "NGN",
            category: "governance",
            milestone_plan_status: "draft",
          },
        ],
        total: 57,
        page: start,
        page_size: 20,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(listProjects).mockResolvedValue(page(1) as never);

    render(<ProjectListShell mode={{ kind: "self" }} />);

    const pager = await screen.findByRole("navigation", {
      name: /project list pages/i,
    });
    expect(pager).toHaveTextContent("Showing 1 to 20 of 57");
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    expect(vi.mocked(listProjects).mock.calls[0][0]).toMatchObject({
      query: { role: "operator", page: 1, page_size: 20 },
    });

    vi.mocked(listProjects).mockResolvedValue(page(2) as never);
    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() =>
      expect(
        vi
          .mocked(listProjects)
          .mock.calls.some((call) => call[0]?.query?.page === 2),
      ).toBe(true),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("navigation", { name: /project list pages/i }),
      ).toHaveTextContent("Showing 21 to 40 of 57"),
    );
  });

  it("counts the whole list in the tab badge, not just the page", async () => {
    // The badge read openProjects.length, so a 57-Project Operator saw "20".
    // Both roles, because the tab bar only renders when there is more than one.
    tokenRoles.current = ["operator", "contributor"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 57, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<ProjectListShell mode={{ kind: "self" }} />);

    const tab = await screen.findByRole("tab", { name: /posted/i });
    expect(tab).toHaveTextContent("57");
  });

  it("disables Next on the final page", async () => {
    tokenRoles.current = ["operator"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 12, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<ProjectListShell mode={{ kind: "self" }} />);

    expect(
      await screen.findByRole("navigation", { name: /project list pages/i }),
    ).toHaveTextContent("Showing 1 to 12 of 12");
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("calls listProjects when mode is self", async () => {
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<ProjectListShell mode={{ kind: "self" }} />);

    await waitFor(() => {
      expect(listProjects).toHaveBeenCalledWith(
        expect.objectContaining({
          query: { page: 1, page_size: 20, role: "operator" },
        })
      );
    });
  });
});
