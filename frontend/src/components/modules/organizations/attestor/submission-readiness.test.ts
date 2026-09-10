import { describe, it, expect } from "vitest";
import { submissionReadiness } from "./attestor-application-tab";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";

/** A fully complete application shell for readiness assertions. */
function completeApp(): OrgAttestorApplicationResponse {
  return {
    status: "needs_info",
    legal_name: "Meridian Ltd.",
    registration_number: "RC123456",
    credentials_summary: "Ten years of audit experience across sectors.",
    professional_references: "Jane Doe, jane@example.com",
    incorporation_doc_keys: ["kyb/org-1/app/uuid-cert.pdf"],
    payout_account_id: "11111111-1111-1111-1111-111111111111",
    sectors: ["private_equity"],
    functions: ["compliance"],
    jurisdictions: ["united_states"],
  } as never;
}

describe("submissionReadiness", () => {
  it("is not ready before an application exists", () => {
    const r = submissionReadiness(null);
    expect(r.ready).toBe(false);
    expect(r.hint).toMatch(/save a draft/i);
  });

  it("flags missing application details", () => {
    // Legal identity is not among them: the org is business-verified before it
    // can apply, so this checks only what the application itself owns.
    const r = submissionReadiness({
      ...completeApp(),
      credentials_summary: "",
    } as never);
    expect(r.ready).toBe(false);
    expect(r.hint).toMatch(/application details/i);
  });

  it("flags a missing payout account once details and a document are present", () => {
    const r = submissionReadiness({
      ...completeApp(),
      payout_account_id: null,
    } as never);
    expect(r.ready).toBe(false);
    expect(r.hint).toMatch(/payout account/i);
  });

  it("is ready when every required field, a document, and a payout account are present", () => {
    const r = submissionReadiness(completeApp());
    expect(r.ready).toBe(true);
  });
});
