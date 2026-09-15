/**
 * Unit coverage for the attestation request form's brief length limits: each
 * free-text field stops at the server's 2,000-character cap and counts down.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AttestationRequestForm } from "@/components/modules/attestation/attestation-request-form";
import {
  getExploreFrameworkDetail,
  listAttestationReviewTypes,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAttestationReviewTypes: vi.fn(() =>
    Promise.resolve({ data: { review_types: [] }, error: undefined, response: { ok: true } }),
  ),
  getExploreFrameworkDetail: vi.fn(() =>
    Promise.resolve({ data: { attestation_badges: [] }, error: undefined, response: { ok: true } }),
  ),
}));

const REVIEW_TYPES = [
  { key: "quality", label: "Quality", description: "Is it complete and accurate?", fee_amount: "150000.00", currency: "NGN" },
  { key: "compliance", label: "Compliance", description: "Does it meet the law?", fee_amount: "350000.00", currency: "NGN" },
  { key: "expert", label: "Expert", description: "Is it technically sound?", fee_amount: "750000.00", currency: "NGN" },
  { key: "provenance", label: "Provenance", description: "Is it original?", fee_amount: "150000.00", currency: "NGN" },
];

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

describe("AttestationRequestForm review type details", () => {
  it("shows each review type's fee and describes the chosen one", async () => {
    vi.mocked(listAttestationReviewTypes).mockResolvedValue({
      data: { review_types: REVIEW_TYPES },
      error: undefined,
      response: { ok: true },
    } as never);
    renderForm();

    const compliance = await screen.findByRole("option", { name: /Compliance · ₦350,000/ });
    expect(compliance).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Review type/i), { target: { value: "compliance" } });

    expect(screen.getByText("Does it meet the law?")).toBeInTheDocument();
  });

  it("disables a review type already attested for the framework's current version", async () => {
    vi.mocked(listAttestationReviewTypes).mockResolvedValue({
      data: { review_types: REVIEW_TYPES },
      error: undefined,
      response: { ok: true },
    } as never);
    vi.mocked(getExploreFrameworkDetail).mockResolvedValue({
      data: {
        attestation_badges: [
          { review_type: "quality", outcome: "conditional", newer_version_exists: false },
        ],
      },
      error: undefined,
      response: { ok: true },
    } as never);
    renderForm();

    const quality = (await screen.findByRole("option", {
      name: /Quality.*already attested/i,
    })) as HTMLOptionElement;
    expect(quality.disabled).toBe(true);
    expect(getExploreFrameworkDetail).toHaveBeenCalledWith(
      expect.objectContaining({ path: { framework_id: "fw-1" } }),
    );
  });
});
