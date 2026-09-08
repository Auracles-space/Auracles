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

    expect(await screen.findByRole("link", { name: /controls rollout/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/projects/proj-1",
    );
    expect(screen.getByRole("link", { name: /post project/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/projects?view=create",
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
        expect.objectContaining({ query: { role: "operator" } })
      );
    });
  });
});
