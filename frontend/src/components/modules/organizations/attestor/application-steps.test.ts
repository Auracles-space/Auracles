/**
 * Step and review-stage logic for the owner's attestor application.
 *
 * The owner works through five steps before submitting; everything after
 * submission (review, calibration trial, approval, activation) is admin-driven
 * and read as one review stage.
 */
import { describe, expect, it } from "vitest";

import {
  initialStep,
  reviewStage,
  stageIndex,
  stepComplete,
  submissionReadiness,
} from "./application-steps";

/** An application with every owner step done, in the given status. */
function complete(overrides: Record<string, unknown> = {}) {
  return {
    status: "draft",
    credentials_summary: "Ten years of audit experience across sectors.",
    professional_references: "Jane Doe, jane@example.com",
    sectors: ["private_equity"],
    functions: ["compliance"],
    jurisdictions: ["nigeria"],
    coi_signed_at: "2026-09-15T00:00:00Z",
    confidentiality_signed_at: "2026-09-15T00:00:00Z",
    tax_document_key: "tax/doc.pdf",
    payout_account_id: "pa-1",
    trial_member_id: "member-1",
    admin_feedback: null,
    ...overrides,
  } as never;
}

describe("application steps", () => {
  it("opens on the first incomplete owner step, or Submit when all are done", () => {
    expect(initialStep(null)).toBe("details");
    expect(initialStep(complete({ tax_document_key: null }))).toBe("tax");
    expect(initialStep(complete())).toBe("submit");
  });

  it("needs both undertakings signed", () => {
    expect(stepComplete(complete({ coi_signed_at: null }), "undertakings")).toBe(false);
    expect(stepComplete(complete(), "undertakings")).toBe(true);
  });

  it("marks Submit complete once the application has left draft", () => {
    expect(stepComplete(complete(), "submit")).toBe(false);
    expect(stepComplete(complete({ status: "submitted" }), "submit")).toBe(true);
  });
});

describe("reviewStage", () => {
  it("explains an in-review application before the trial starts", () => {
    const stage = reviewStage(complete({ status: "submitted" }), undefined);
    expect(stage.status).toBe("in_review");
    expect(stage.detail).toMatch(/start the calibration trial/i);
    expect(stageIndex(complete({ status: "submitted" }), undefined)).toBe(1);
  });

  it("follows the trial through to approval", () => {
    expect(reviewStage(complete({ status: "submitted", trial_status: "assigned" }), undefined).status).toBe("pending");
    expect(reviewStage(complete({ status: "submitted", trial_status: "submitted" }), undefined).title).toMatch(/grad/i);
    const passed = complete({ status: "submitted", trial_status: "passed" });
    expect(reviewStage(passed, undefined).detail).toMatch(/final approval/i);
    expect(stageIndex(passed, undefined)).toBe(2);
  });

  it("reads active once the capability is active", () => {
    expect(reviewStage(complete({ status: "approved" }), "active").status).toBe("active");
    expect(stageIndex(complete({ status: "approved" }), "active")).toBe(3);
  });
});

describe("submissionReadiness", () => {
  it("names every owner step still missing", () => {
    const readiness = submissionReadiness(
      complete({ tax_document_key: null, trial_member_id: null }),
    );
    expect(readiness.ready).toBe(false);
    expect(readiness.hint).toMatch(/Tax document/);
    expect(readiness.hint).toMatch(/Trial member/);
  });

  it("is ready when every owner step is done", () => {
    expect(submissionReadiness(complete()).ready).toBe(true);
  });
});
