import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FrameworkForm } from "@/components/modules/frameworks/framework-form";

describe("FrameworkForm", () => {
  function fillRequiredFields(fe: typeof fireEvent, sc: typeof screen) {
    fe.change(sc.getByLabelText(/framework title/i), { target: { value: "Title" } });
    fe.change(sc.getByLabelText(/description/i), { target: { value: "Desc" } });
    fe.change(sc.getByLabelText(/base price/i), { target: { value: "100" } });
    const singleUser = sc.getByRole("checkbox", { name: /single user/i });
    if (!(singleUser as HTMLInputElement).checked) {
      fe.click(singleUser);
    }
    fe.change(sc.getByLabelText(/sector/i), { target: { value: "healthcare" } });
    fe.change(sc.getByLabelText(/industry/i), { target: { value: "healthcare_providers" } });
    fe.change(sc.getByLabelText(/function/i), { target: { value: "engineering" } });
    fe.change(sc.getByLabelText(/category/i), { target: { value: "toolkit" } });
    fe.change(sc.getByLabelText(/organization size/i), { target: { value: "enterprise" } });
  }
  it("uses framework type options for the category field", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    const category = screen.getByLabelText(/category/i);
    const options = within(category).getAllByRole("option");

    expect(options.map((option) => option.textContent)).toEqual([
      "Framework",
      "Playbook",
      "Standard Operating Procedure",
      "Policy",
      "Template",
      "Toolkit",
      "Assessment",
      "Control Matrix",
      "Workflow",
      "Training Program",
    ]);
    expect(options.map((option) => option.getAttribute("value"))).toEqual([
      "framework",
      "playbook",
      "sop",
      "policy",
      "template",
      "toolkit",
      "assessment",
      "control_matrix",
      "workflow",
      "training_program",
    ]);
  });

  it("disables submit until required fields are valid", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    const submit = screen.getByRole("button", { name: /save framework/i });
    // Title and description start empty, so the button is gated off.
    expect(submit).toBeDisabled();

    fillRequiredFields(fireEvent, screen);

    // Now all required fields are filled.
    expect(submit).toBeEnabled();
  });

  it("submits sector, industry, function, organization, and framework type", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FrameworkForm onSubmit={onSubmit} />);

    fillRequiredFields(fireEvent, screen);
    
    // Explicitly override to ensure these specific values are tested
    fireEvent.change(screen.getByLabelText(/framework title/i), {
      target: { value: "Healthcare Engineering Toolkit" },
    });
    fireEvent.change(screen.getByLabelText(/sector/i), {
      target: { value: "healthcare" },
    });
    fireEvent.change(screen.getByLabelText(/industry/i), {
      target: { value: "healthcare_providers" },
    });
    fireEvent.change(screen.getByLabelText(/function/i), {
      target: { value: "engineering" },
    });
    fireEvent.change(screen.getByLabelText(/category/i), {
      target: { value: "toolkit" },
    });
    fireEvent.change(screen.getByLabelText(/organization size/i), {
      target: { value: "enterprise" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save framework/i }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          category: "toolkit",
          function: "engineering",
          industry: "healthcare_providers",
          org_size: "enterprise",
          sector: "healthcare",
        }),
      );
    });
  });

  it("submits complexity, lifecycle stage, and jurisdiction when chosen", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FrameworkForm onSubmit={onSubmit} />);

    fillRequiredFields(fireEvent, screen);
    fireEvent.change(screen.getByLabelText(/complexity/i), {
      target: { value: "4" },
    });
    fireEvent.change(screen.getByLabelText(/lifecycle stage/i), {
      target: { value: "growth" },
    });
    fireEvent.change(screen.getByLabelText(/jurisdiction/i), {
      target: { value: "united_states" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save framework/i }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          complexity: 4,
          jurisdiction: "united_states",
          lifecycle_stage: "growth",
        }),
      );
    });
  });

  it("omits optional complexity, lifecycle, and jurisdiction when left unset", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FrameworkForm onSubmit={onSubmit} />);

    fillRequiredFields(fireEvent, screen);
    fireEvent.click(screen.getByRole("button", { name: /save framework/i }));

    await waitFor(() => {
      const payload = onSubmit.mock.calls[0][0];
      expect(payload).not.toHaveProperty("complexity");
      expect(payload).not.toHaveProperty("lifecycle_stage");
      expect(payload).not.toHaveProperty("jurisdiction");
    });
  });

  it("submits selected license types", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FrameworkForm onSubmit={onSubmit} />);

    fillRequiredFields(fireEvent, screen);
    
    // We expect single user since fillRequiredFields checks it
    fireEvent.click(screen.getByRole("button", { name: /save framework/i }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          pricing: expect.objectContaining({
            license_types: ["single_user"],
          }),
        }),
      );
    });
  });

  it("shows the organizational tier while keeping team and enterprise hidden", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    expect(
      screen.getByRole("checkbox", { name: /single user/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /organizational/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /team/i })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /enterprise/i })).toBeNull();
  });

  it("allows single-user tier to be unselected", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    fillRequiredFields(fireEvent, screen);
    
    const submit = screen.getByRole("button", { name: /save framework/i });
    expect(submit).toBeEnabled();

    const singleUser = screen.getByRole("checkbox", { name: /single user/i });
    expect(singleUser).toBeChecked();

    fireEvent.click(singleUser);

    expect(singleUser).not.toBeChecked();
    expect(submit).toBeDisabled(); // Disabled because 0 license types selected
  });

  it("constrains the price input to a two-decimal currency amount", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    const price = screen.getByLabelText(/base price/i);
    expect(price).toHaveAttribute("inputmode", "decimal");

    fireEvent.change(price, { target: { value: "12a.9999" } });
    expect(price).toHaveValue("12.99");
  });

  it("commits tags as chips and submits the deduplicated list", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FrameworkForm onSubmit={onSubmit} />);

    fillRequiredFields(fireEvent, screen);

    const tags = screen.getByLabelText(/tags/i);
    fireEvent.change(tags, { target: { value: "python" } });
    fireEvent.keyDown(tags, { key: "Enter" });
    fireEvent.change(tags, { target: { value: "aws" } });
    fireEvent.keyDown(tags, { key: "Enter" });
    // Duplicate is ignored.
    fireEvent.change(tags, { target: { value: "python" } });
    fireEvent.keyDown(tags, { key: "Enter" });

    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("aws")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /save framework/i }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ tags: ["python", "aws"] }),
      );
    });
  });

  it("removes a tag chip", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    const tags = screen.getByLabelText(/tags/i);
    fireEvent.change(tags, { target: { value: "python" } });
    fireEvent.keyDown(tags, { key: "Enter" });

    expect(screen.getByText("python")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /remove python/i }));
    expect(screen.queryByText("python")).not.toBeInTheDocument();
  });

  it("caps the tag list at five tags", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    const tags = screen.getByLabelText(/tags/i);
    for (const tag of ["a", "b", "c", "d", "e"]) {
      fireEvent.change(tags, { target: { value: tag } });
      fireEvent.keyDown(tags, { key: "Enter" });
    }
    // Sixth tag is rejected.
    fireEvent.change(tags, { target: { value: "f" } });
    fireEvent.keyDown(tags, { key: "Enter" });

    expect(screen.queryByText("f")).not.toBeInTheDocument();
    expect(tags).toBeDisabled();
  });
});
