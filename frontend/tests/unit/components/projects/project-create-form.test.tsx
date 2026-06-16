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
}));

describe("ProjectCreateForm", () => {
  beforeEach(() => {
    vi.mocked(createProject).mockReset();
    push.mockReset();
  });

  it("disables submit until title and description are filled", () => {
    render(<ProjectCreateForm />);

    const submit = screen.getByRole("button", { name: /post project/i });
    // Title and description start empty, so the button is gated off.
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^title$/i), {
      target: { value: "Procurement Playbook" },
    });
    fireEvent.change(screen.getByLabelText(/^description$/i), {
      target: { value: "Build a procurement operating model." },
    });

    // Remaining required fields default to valid values.
    expect(submit).toBeEnabled();
  });

  it("creates a project and routes to its workspace", async () => {
    vi.mocked(createProject).mockResolvedValue({
      data: { id: "proj-1" },
      error: undefined,
      response: new Response(null, { status: 201 }),
    });

    render(<ProjectCreateForm />);
    fireEvent.change(screen.getByLabelText(/^title$/i), {
      target: { value: "Procurement Playbook" },
    });
    fireEvent.change(screen.getByLabelText(/^description$/i), {
      target: { value: "Build a procurement operating model." },
    });
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
    fireEvent.change(screen.getByLabelText(/^title$/i), {
      target: { value: "Procurement Playbook" },
    });
    fireEvent.change(screen.getByLabelText(/^description$/i), {
      target: { value: "Build a procurement operating model." },
    });
    fireEvent.click(screen.getByRole("button", { name: /post project/i }));

    expect(
      await screen.findByText(/active project cap reached/i),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
