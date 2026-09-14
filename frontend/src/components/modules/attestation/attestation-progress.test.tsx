import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import {
  AttestationProgress,
  attestationProgressSteps,
} from "./attestation-progress";

/** Build a requestor-visible attestation in the given status. */
function attestation(
  overrides: Partial<AttestationRequestResponse> = {},
): AttestationRequestResponse {
  return {
    id: "att-1",
    requestor_id: "user-1",
    attestor_org_id: null,
    target_type: "framework",
    target_id: "fw-1",
    status: "matching",
    outcome: null,
    fee_amount: "1200.00",
    currency: "NGN",
    escrow_id: null,
    requested_jurisdictions: [],
    requested_specializations: [],
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-02T00:00:00Z",
    ...overrides,
  } as AttestationRequestResponse;
}

describe("attestationProgressSteps", () => {
  it("marks everything before the current step as done", () => {
    const steps = attestationProgressSteps(attestation({ status: "in_review" }));

    expect(steps.map((step) => step.label)).toEqual([
      "Requested",
      "Paid",
      "Attestor assigned",
      "In review",
      "Report",
      "Closed",
    ]);
    expect(steps.map((step) => step.state)).toEqual([
      "done",
      "done",
      "done",
      "current",
      "upcoming",
      "upcoming",
    ]);
  });

  it("puts an unpaid request on the payment step", () => {
    const steps = attestationProgressSteps(
      attestation({ status: "pending_fee" }),
    );
    expect(steps[0].state).toBe("done");
    expect(steps[1].state).toBe("current");
  });

  it("treats a released request as finished end to end", () => {
    const steps = attestationProgressSteps(attestation({ status: "released" }));
    // Nothing is pending once the fee is released, so no stage reads as current.
    expect(steps.every((step) => step.state === "done")).toBe(true);
  });

  it("ends a withdrawn request on a neutral final step", () => {
    const steps = attestationProgressSteps(
      attestation({ status: "cancelled", escrow_id: "esc-1" }),
    );
    expect(steps[5].label).toBe("Ended");
    expect(steps[5].state).toBe("current");
    expect(steps[1].state).toBe("done");
    expect(steps[2].state).toBe("upcoming");
  });

  it("ends a refunded request on the same neutral final step", () => {
    const steps = attestationProgressSteps(
      attestation({ status: "refunded", attestor_org_id: "org-1" }),
    );
    expect(steps[5].label).toBe("Ended");
    expect(steps[2].state).toBe("done");
  });
});

describe("AttestationProgress", () => {
  it("renders the ordered steps and names the current one", () => {
    render(<AttestationProgress attestation={attestation({ status: "in_review" })} />);

    const list = screen.getByRole("list", { name: "Request progress" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    expect(items[3]).toHaveTextContent("In review");
    expect(items[3]).toHaveAttribute("aria-current", "step");
  });
});
