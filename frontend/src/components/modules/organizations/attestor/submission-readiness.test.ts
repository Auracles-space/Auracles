import { describe, it, expect } from "vitest";
import { submissionReadiness } from "./application-steps";
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
    coi_signed_at: "2026-09-15T00:00:00Z",
    confidentiality_signed_at: "2026-09-15T00:00:00Z",
    tax_document_key: "tax/org-1/doc.pdf",
    trial_member_id: "22222222-2222-2222-2222-222222222222",
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

  it("flags a missing payout account once the details are complete", () => {
    const r = submissionReadiness({
      ...completeApp(),
      payout_account_id: null,
    } as never);
    expect(r.ready).toBe(false);
    expect(r.hint).toMatch(/payout account/i);
  });

  it("is ready when every owner step is done", () => {
    const r = submissionReadiness(completeApp());
    expect(r.ready).toBe(true);
  });
});
