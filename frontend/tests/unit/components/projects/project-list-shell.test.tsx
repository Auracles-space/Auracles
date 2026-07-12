import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectListShell } from "@/components/modules/projects/project-list-shell";

const { push, replace } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
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
    getState: () => ({ roles: [] }), // default empty roles
  },
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listProjects: vi.fn(),
  listOrgProjects: vi.fn(),
}));

describe("ProjectListShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
