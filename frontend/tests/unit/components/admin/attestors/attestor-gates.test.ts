import { describe, expect, it } from "vitest";

import { computeGates } from "@/components/modules/admin/attestors/attestor-gates";

function app(overrides: Partial<Parameters<typeof computeGates>[0]> = {}) {
  return {
    id: "app-1",
    org_id: "org-1",
    org_name: "Audit Ltd",
    status: "submitted",
    kyb_status: "unverified",
    trial_status: null,
    capability_status: null,
    admin_feedback: null,
    created_at: "2026-07-07T12:00:00Z",
    reviewed_at: null,
    ...overrides,
  };
}

describe("computeGates", () => {
  it("blocks everything but needs-info/reject until business verification is done", () => {
    const gates = computeGates(app());

    expect(gates.kybDone).toBe(false);
    expect(gates.canStartTrial).toBe(false);
    expect(gates.canApprove).toBe(false);
    expect(gates.canNeedsInfo).toBe(true);
    expect(gates.canReject).toBe(true);
    expect(gates.nextStep).toBe("Verify the organization first.");
  });

  it("offers the trial once verified and nothing is assigned", () => {
    const gates = computeGates(app({ kyb_status: "verified" }));

    expect(gates.canStartTrial).toBe(true);
    expect(gates.canApprove).toBe(false);
    expect(gates.nextStep).toBe("Start the calibration trial.");
  });

  it("waits on the nominee while a trial is assigned", () => {
    const gates = computeGates(app({ kyb_status: "verified", trial_status: "assigned" }));

    expect(gates.canStartTrial).toBe(false);
    expect(gates.awaitingNominee).toBe(true);
    expect(gates.nextStep).toBe("Waiting on the nominee to complete the trial.");
  });

  it("asks for a grade decision when the trial is submitted", () => {
    const gates = computeGates(app({ kyb_status: "verified", trial_status: "submitted" }));

    expect(gates.trialSubmitted).toBe(true);
    expect(gates.canApprove).toBe(false);
    expect(gates.nextStep).toBe("Grade the submitted trial.");
  });

  it("lets a failed trial be started again", () => {
    const gates = computeGates(app({ kyb_status: "verified", trial_status: "failed" }));

    expect(gates.canStartTrial).toBe(true);
    expect(gates.nextStep).toBe("Trial failed. Start it again for another attempt.");
  });

  it("allows approval only when verified and the trial passed", () => {
    const gates = computeGates(app({ kyb_status: "verified", trial_status: "passed" }));

    expect(gates.canApprove).toBe(true);
    expect(gates.canStartTrial).toBe(false);
    expect(gates.nextStep).toBe("All gates met. Ready to approve.");
  });

  it("does not approve from needs_info even when gates are met", () => {
    const gates = computeGates(
      app({ status: "needs_info", kyb_status: "verified", trial_status: "passed" }),
    );

    expect(gates.canApprove).toBe(false);
    expect(gates.canNeedsInfo).toBe(false);
    expect(gates.nextStep).toBe("Waiting on the organization to resubmit.");
  });

  it("offers no application actions once decided", () => {
    const approved = computeGates(app({ status: "approved", capability_status: "active" }));
    const rejected = computeGates(app({ status: "rejected" }));

    expect(approved.decided).toBe(true);
    expect(approved.canReject).toBe(false);
    expect(approved.nextStep).toBeNull();
    expect(rejected.canReject).toBe(false);
  });

  it("enables only the valid capability transitions", () => {
    expect(computeGates(app({ status: "approved", capability_status: "active" })).capability)
      .toEqual({ canSuspend: true, canReinstate: false, canRevoke: true });
    expect(
      computeGates(app({ status: "approved", capability_status: "suspended" })).capability,
    ).toEqual({ canSuspend: false, canReinstate: true, canRevoke: true });
    expect(computeGates(app({ status: "approved", capability_status: "revoked" })).capability)
      .toEqual({ canSuspend: false, canReinstate: false, canRevoke: false });
  });
});
