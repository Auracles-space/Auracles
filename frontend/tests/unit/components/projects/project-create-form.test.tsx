import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectCreateForm } from "@/components/modules/projects/project-create-form";
import { createProject } from "@/lib/generated/sdk.gen";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  createProject: vi.fn(),
  createOrgProject: vi.fn(),
}));

function fillForm() {
  fireEvent.change(screen.getByLabelText(/^title$/i), {
    target: { value: "Procurement Playbook" },
  });
  fireEvent.change(screen.getByLabelText(/^description$/i), {
    target: { value: "Build a procurement operating model." },
  });
  fireEvent.change(screen.getByLabelText(/^category$/i), {
    target: { value: "operations" },
  });
  fireEvent.change(screen.getByLabelText(/^minimum budget$/i), {
    target: { value: "1000.00" },
  });
  fireEvent.change(screen.getByLabelText(/^maximum budget$/i), {
    target: { value: "2000.00" },
  });
  fireEvent.change(screen.getByLabelText(/^deliverable name$/i), {
    target: { value: "Implementation playbook" },
  });
  fireEvent.change(screen.getByLabelText(/^deliverable description$/i), {
    target: { value: "Implementation guide and supporting templates." },
  });
}

describe("ProjectCreateForm", () => {
  beforeEach(() => {
    vi.mocked(createProject).mockReset();
    push.mockReset();
  });

  it("disables submit until all required fields are filled", () => {
    render(<ProjectCreateForm />);

    const submit = screen.getByRole("button", { name: /post project/i });
    expect(submit).toBeDisabled();

    fillForm();

    expect(submit).toBeEnabled();
  });

  it("keeps submit disabled if minimum budget is greater than maximum budget", () => {
    render(<ProjectCreateForm />);
    const submit = screen.getByRole("button", { name: /post project/i });

    fillForm();
    fireEvent.change(screen.getByLabelText(/^minimum budget$/i), {
      target: { value: "3000.00" },
    });

    expect(submit).toBeDisabled();
    expect(
      screen.getByText(/maximum budget must be greater than or equal to minimum budget/i),
    ).toBeInTheDocument();
  });

  it("keeps submit disabled if deadline is in the past", () => {
    render(<ProjectCreateForm />);
    const submit = screen.getByRole("button", { name: /post project/i });

    fillForm();

    const pastDate = new Date();
    pastDate.setDate(pastDate.getDate() - 1);
    const pastDateString = pastDate.toISOString().split("T")[0];

    fireEvent.change(screen.getByLabelText(/^deadline$/i), {
      target: { value: pastDateString },
    });

    expect(submit).toBeDisabled();
    expect(
      screen.getByText(/deadline cannot be in the past/i),
    ).toBeInTheDocument();
  });

  it("creates a project and routes to its workspace", async () => {
    vi.mocked(createProject).mockResolvedValue({
      data: { id: "proj-1" },
      error: undefined,
      response: new Response(null, { status: 201 }),
    });

    render(<ProjectCreateForm />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /post project/i }));

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/projects/proj-1");
    });
    expect(vi.mocked(createProject)).toHaveBeenCalledTimes(1);
  });

  it("shows the error detail when creation is rejected", async () => {
    vi.mocked(createProject).mockResolvedValue({
      data: undefined,
      error: { detail: "Active project cap reached." },
      response: new Response(null, { status: 409 }),
    });

    render(<ProjectCreateForm />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /post project/i }));

    expect(
      await screen.findByText(/active project cap reached/i),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("creates an org project when mode is org", async () => {
    const { createOrgProject } = await import("@/lib/generated/sdk.gen");
    vi.mocked(createOrgProject).mockResolvedValue({
      data: { id: "proj-org-1" },
      error: undefined,
      response: new Response(null, { status: 201 }),
    });

    render(<ProjectCreateForm mode={{ kind: "org", orgId: "org-1" }} />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /post project/i }));

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/projects/proj-org-1");
    });
    expect(vi.mocked(createOrgProject)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" } })
    );
  });
});
