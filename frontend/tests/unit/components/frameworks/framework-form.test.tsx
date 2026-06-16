import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FrameworkForm } from "@/components/modules/frameworks/framework-form";

describe("FrameworkForm", () => {
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

    fireEvent.change(screen.getByLabelText(/framework title/i), {
      target: { value: "Healthcare Engineering Toolkit" },
    });
    fireEvent.change(screen.getByLabelText(/description/i), {
      target: { value: "A healthcare software engineering delivery system." },
    });

    // Price defaults to a positive number; required fields are now valid.
    expect(submit).toBeEnabled();
  });

  it("submits sector, industry, function, organization, and framework type", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FrameworkForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText(/framework title/i), {
      target: { value: "Healthcare Engineering Toolkit" },
    });
    fireEvent.change(screen.getByLabelText(/description/i), {
      target: {
        value: "A healthcare software engineering delivery system.",
      },
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
});
