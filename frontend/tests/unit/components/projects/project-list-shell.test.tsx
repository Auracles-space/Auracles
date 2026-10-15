import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectListShell } from "@/components/modules/projects/project-list-shell";

const { push, replace, searchParams, tokenRoles } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  // Mutable, because Next delivers a tab change as a new URL the component
  // re-reads. A frozen value made every tab-switch test vacuous.
  searchParams: { current: new URLSearchParams() },
  tokenRoles: { current: [] as string[] },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/projects",
  useRouter: () => ({ push, replace }),
  useSearchParams: () => searchParams.current,
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
    searchParams.current = new URLSearchParams();
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

  it("sends the feed filters the URL carries", async () => {
    tokenRoles.current = ["contributor"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 0, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    searchParams.current = new URLSearchParams(
      "tab=open&q=payroll&category=compliance&budget_at_least=1000&sort=budget_desc",
    );

    render(<ProjectListShell mode={{ kind: "self" }} />);

    await waitFor(() => expect(listProjects).toHaveBeenCalled());
    const feedCall = vi
      .mocked(listProjects)
      .mock.calls.find((call) => call[0]?.query?.scope === "open");
    expect(feedCall?.[0].query).toMatchObject({
      budget_at_least: "1000",
      category: "compliance",
      q: "payroll",
      sort: "budget_desc",
    });
  });

  it("refuses a sort the API does not accept", async () => {
    // A query string is user input. Passing it through earned a 422 and broke
    // the page on a value someone typed by hand.
    tokenRoles.current = ["contributor"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 0, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    searchParams.current = new URLSearchParams("tab=open&sort=cheapest");

    render(<ProjectListShell mode={{ kind: "self" }} />);

    await waitFor(() => expect(listProjects).toHaveBeenCalled());
    const feedCall = vi
      .mocked(listProjects)
      .mock.calls.find((call) => call[0]?.query?.scope === "open");
    expect(feedCall?.[0].query.sort).toBe("newest");
  });

  it("writes a chosen filter to the URL and drops a cleared one", async () => {
    tokenRoles.current = ["contributor"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 0, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    searchParams.current = new URLSearchParams("tab=open");

    const first = render(<ProjectListShell mode={{ kind: "self" }} />);

    fireEvent.change(await screen.findByLabelText(/^category$/i), {
      target: { value: "compliance" },
    });
    expect(replace).toHaveBeenCalledWith(
      "/projects?tab=open&category=compliance",
      { scroll: false },
    );

    // Clearing removes the param rather than leaving category= behind, because
    // these URLs are meant to be shared. Unmounted first so the second render
    // is the only shell on screen and the query below is unambiguous.
    first.unmount();
    searchParams.current = new URLSearchParams("tab=open&category=compliance");
    replace.mockClear();
    render(<ProjectListShell mode={{ kind: "self" }} />);

    fireEvent.change(await screen.findByLabelText(/^category$/i), {
      target: { value: "" },
    });

    expect(replace).toHaveBeenCalledWith("/projects?tab=open", {
      scroll: false,
    });
  });

  it("restarts paging when a filter narrows the result set", async () => {
    // Page 3 of the old result set is meaningless once the set changes, and
    // usually renders empty.
    tokenRoles.current = ["contributor"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 57, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    searchParams.current = new URLSearchParams("tab=open");

    render(<ProjectListShell mode={{ kind: "self" }} />);
    fireEvent.click(await screen.findByRole("button", { name: /next/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("navigation", { name: /project list pages/i }),
      ).toHaveTextContent("Showing 21 to 40 of 57"),
    );

    fireEvent.change(screen.getByLabelText(/^category$/i), {
      target: { value: "compliance" },
    });

    await waitFor(() =>
      expect(
        screen.getByRole("navigation", { name: /project list pages/i }),
      ).toHaveTextContent("Showing 1 to 20 of 57"),
    );
  });

  it("offers a status filter on an owner's own list, not a search box", async () => {
    tokenRoles.current = ["operator"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 0, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    searchParams.current = new URLSearchParams("tab=posted&status=closed");

    render(<ProjectListShell mode={{ kind: "self" }} />);

    expect(await screen.findByLabelText(/^status$/i)).toHaveValue("closed");
    expect(screen.queryByLabelText(/search projects/i)).not.toBeInTheDocument();
    const ownedCall = vi
      .mocked(listProjects)
      .mock.calls.find((call) => call[0]?.query?.role === "operator");
    expect(ownedCall?.[0].query).toMatchObject({ status: "closed" });
  });

  it("switches tab without refetching anything", async () => {
    // Paging made the active tab a fetch dependency, so every tab change tore
    // the lists down, flashed skeletons and reissued three requests — the page
    // used to switch tabs as a pure re-render, and it has to go back to that.
    tokenRoles.current = ["operator", "contributor"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 3, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    searchParams.current = new URLSearchParams("tab=open");

    const { rerender } = render(<ProjectListShell mode={{ kind: "self" }} />);
    await waitFor(() => expect(listProjects).toHaveBeenCalledTimes(3));
    const callsAfterLoad = vi.mocked(listProjects).mock.calls.length;

    // The tab moves the way a real navigation moves it: new URL, same instance.
    searchParams.current = new URLSearchParams("tab=posted");
    rerender(<ProjectListShell mode={{ kind: "self" }} />);
    await screen.findByRole("tab", { name: /posted/i });

    expect(vi.mocked(listProjects).mock.calls.length).toBe(callsAfterLoad);
  });

  it("remembers each tab's page instead of resetting it", async () => {
    // Page 4 of Posted and page 1 of Open are independent positions; collapsing
    // them to one counter meant leaving a tab lost your place in it.
    tokenRoles.current = ["operator", "contributor"];
    const { listProjects } = await import("@/lib/generated/sdk.gen");
    vi.mocked(listProjects).mockResolvedValue({
      data: { projects: [], total: 57, page: 1, page_size: 20 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    searchParams.current = new URLSearchParams("tab=posted");

    const { rerender } = render(<ProjectListShell mode={{ kind: "self" }} />);
    fireEvent.click(await screen.findByRole("button", { name: /next/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("navigation", { name: /project list pages/i }),
      ).toHaveTextContent("Showing 21 to 40 of 57"),
    );

    searchParams.current = new URLSearchParams("tab=open");
    rerender(<ProjectListShell mode={{ kind: "self" }} />);
    expect(
      screen.getByRole("navigation", { name: /project list pages/i }),
    ).toHaveTextContent("Showing 1 to 20 of 57");

    searchParams.current = new URLSearchParams("tab=posted");
    rerender(<ProjectListShell mode={{ kind: "self" }} />);
    expect(
      screen.getByRole("navigation", { name: /project list pages/i }),
    ).toHaveTextContent("Showing 21 to 40 of 57");
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
