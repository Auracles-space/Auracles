/**
 * Unit coverage for the attestation request form's brief length limits: each
 * free-text field stops at the server's 2,000-character cap and counts down.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AttestationRequestForm } from "@/components/modules/attestation/attestation-request-form";

function renderForm() {
  render(
    <AttestationRequestForm
      defaultOpen
      myFrameworks={[]}
      onSubmit={vi.fn(async () => false)}
      pinned={{ id: "fw-1", title: "Seed-Stage Playbook", external: false }}
      submitting={false}
    />,
  );
}

describe("AttestationRequestForm brief limits", () => {
  it.each(["What it does", "Use case", "Focus areas", "Desired outcome"])(
    "caps %s at 2,000 characters with a live counter",
    (label) => {
      renderForm();

      const field = screen.getByLabelText(new RegExp(label, "i"));
      expect(field).toHaveAttribute("maxLength", "2000");

      fireEvent.change(field, { target: { value: "Hello" } });

      expect(screen.getByText("5 / 2000")).toBeInTheDocument();
    },
  );
});

describe("AttestationRequestForm review types already in progress", () => {
  it("disables a review type that is already in progress for the framework", () => {
    render(
      <AttestationRequestForm
        defaultOpen
        inFlight={[{ id: "att-1", target_id: "fw-1", review_type: "quality", status: "offered" }]}
        myFrameworks={[]}
        onSubmit={vi.fn(async () => false)}
        pinned={{ id: "fw-1", title: "Seed-Stage Playbook", external: false }}
        submitting={false}
      />,
    );

    const quality = screen.getByRole("option", { name: /Quality/ }) as HTMLOptionElement;
    expect(quality.disabled).toBe(true);
    expect(quality.textContent).toMatch(/in progress/i);
    expect(
      (screen.getByRole("option", { name: "Compliance" }) as HTMLOptionElement).disabled,
    ).toBe(false);
  });
});
