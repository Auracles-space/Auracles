import { describe, expect, it } from "vitest";

import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import {
  formatAttestationDate,
  requestorNextStep,
} from "./requestor-next-step";

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

describe("formatAttestationDate", () => {
  it("formats an ISO timestamp as a short British date", () => {
    expect(formatAttestationDate("2026-09-14T10:30:00Z")).toBe("14 Sep 2026");
  });

  it("returns an empty string for a missing date", () => {
    expect(formatAttestationDate(null)).toBe("");
  });
});

describe("requestorNextStep", () => {
  it("waits on the framework owner before payment", () => {
    const step = requestorNextStep(
      attestation({ status: "pending_owner_consent" }),
    );
    expect(step.text).toBe(
      "Waiting for the framework owner to approve your request.",
    );
    expect(step.tone).toBe("warning");
  });

  it("asks for the fee", () => {
    expect(requestorNextStep(attestation({ status: "pending_fee" })).text).toBe(
      "Pay the fee to start matching.",
    );
  });

  it("reads needs_admin as matching, never as an admin problem", () => {
    expect(requestorNextStep(attestation({ status: "needs_admin" })).text).toBe(
      "We are finding an attestor organization. You can still withdraw.",
    );
    expect(requestorNextStep(attestation({ status: "matching" })).text).toBe(
      "We are finding an attestor organization. You can still withdraw.",
    );
  });

  it("says an organization is considering the request while offered", () => {
    expect(requestorNextStep(attestation({ status: "offered" })).text).toBe(
      "An attestor organization is considering your request. You can still withdraw.",
    );
  });

  it("names the reviewing organization and the report deadline", () => {
    const step = requestorNextStep(
      attestation({
        status: "in_review",
        attestor_org_name: "Lagos Assurance",
        completion_due_at: "2026-09-20T00:00:00Z",
      }),
    );
    expect(step.text).toBe(
      "Lagos Assurance is reviewing. Report due 20 Sep 2026.",
    );
    expect(step.date).toBe("2026-09-20T00:00:00Z");
  });

  it("falls back to a generic reviewer when no organization name is exposed", () => {
    expect(
      requestorNextStep(attestation({ status: "accepted" })).text,
    ).toBe("The attestor is reviewing.");
  });

  it("points at the dispute deadline once a report is ready", () => {
    expect(
      requestorNextStep(
        attestation({
          status: "report_submitted",
          dispute_window_ends_at: "2026-09-25T00:00:00Z",
        }),
      ).text,
    ).toBe("Read the report, then accept it or dispute it by 25 Sep 2026.");
  });

  it("explains a revision in progress", () => {
    expect(
      requestorNextStep(
        attestation({
          status: "revision_requested",
          completion_due_at: "2026-09-30T00:00:00Z",
        }),
      ).text,
    ).toBe("The attestor is revising the report. Due 30 Sep 2026.");
  });

  it("gives the dispute decision date", () => {
    const step = requestorNextStep(
      attestation({
        status: "disputed",
        dispute: {
          id: "dis-1",
          status: "open",
          category: "scope_error",
          reason: "Out of scope.",
          resolution_due_at: "2026-10-02T00:00:00Z",
          created_at: "2026-09-26T00:00:00Z",
        },
      }),
    );
    expect(step.text).toBe(
      "Your dispute is with the trust team. Decision due 2 Oct 2026.",
    );
    expect(step.tone).toBe("error");
  });

  it("closes out released and legacy closed requests the same way", () => {
    const expected = "Complete. Rate the attestor and download your invoice.";
    expect(requestorNextStep(attestation({ status: "released" })).text).toBe(
      expected,
    );
    expect(requestorNextStep(attestation({ status: "closed" })).text).toBe(
      expected,
    );
  });

  it("distinguishes a refund from a withdrawal", () => {
    expect(requestorNextStep(attestation({ status: "refunded" })).text).toBe(
      "The fee was refunded.",
    );
    expect(requestorNextStep(attestation({ status: "cancelled" })).text).toBe(
      "You withdrew this request.",
    );
  });
});
