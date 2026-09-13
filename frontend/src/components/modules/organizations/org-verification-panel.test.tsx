import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgVerificationPanel } from "./org-verification-panel";
import {
  addOrgIncorporationDocument,
  getOrgKyb,
  removeOrgIncorporationDocument,
  submitOrgKyb,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  addOrgIncorporationDocument: vi.fn(),
  getOrgKyb: vi.fn(),
  removeOrgIncorporationDocument: vi.fn(),
  submitOrgKyb: vi.fn(),
  upsertLegalProfile: vi.fn(),
}));

/** One KYB status payload in the given state. */
function kyb(overrides: Record<string, unknown> = {}) {
  return {
    response: { ok: true },
    data: {
      country: "NG",
      incorporation_doc_keys: ["org-incorporation-docs/o/p/uuid-uuid-uuid-cert.pdf"],
      kyb_review_notes: null,
      kyb_status: "unverified",
      kyb_submitted_at: null,
      kyb_verified_at: null,
      legal_name: "Acme Attestations Ltd",
      registration_number: "RC123456",
      ...overrides,
    },
  };
}

describe("OrgVerificationPanel", () => {
  beforeEach(() => {
    vi.mocked(getOrgKyb).mockReset();
    vi.mocked(addOrgIncorporationDocument).mockReset();
    vi.mocked(removeOrgIncorporationDocument).mockReset();
    vi.mocked(submitOrgKyb).mockReset();
    vi.mocked(getOrgKyb).mockResolvedValue(kyb() as never);
  });

  it("labels the registration fields for the organization's country", async () => {
    // One flow worldwide, but a Nigerian reader holds an RC number and a CAC
    // certificate, not a generic "registration number".
    render(<OrgVerificationPanel />);

    expect(await screen.findByText(/RC number/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Certificate of Incorporation \(CAC\)/i),
    ).toBeInTheDocument();
  });

  it("submits for review once identity and a document are present", async () => {
    vi.mocked(submitOrgKyb).mockResolvedValue({
      response: { ok: true },
      data: { kyb_status: "pending" },
    } as never);

    render(<OrgVerificationPanel />);

    fireEvent.click(
      await screen.findByRole("button", { name: /Submit for verification/i }),
    );

    await waitFor(() =>
      expect(submitOrgKyb).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1" } }),
      ),
    );
  });

  it("locks a verified organization out of editing its identity", async () => {
    // The badge has to keep meaning what an admin actually checked.
    vi.mocked(getOrgKyb).mockResolvedValue(
      kyb({ kyb_status: "verified", kyb_verified_at: "2026-09-09T00:00:00Z" }) as never,
    );

    render(<OrgVerificationPanel />);

    expect(await screen.findByText("Verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove/i })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Submit for verification/i }),
    ).toBeNull();
  });

  it("shows the reviewer's reason when the organization was rejected", async () => {
    // A rejection the org cannot act on is the same as no answer at all.
    vi.mocked(getOrgKyb).mockResolvedValue(
      kyb({
        kyb_review_notes: "The certificate is unreadable.",
        kyb_status: "rejected",
      }) as never,
    );

    render(<OrgVerificationPanel />);

    expect(
      await screen.findByText("The certificate is unreadable."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Submit for verification/i }),
    ).toBeInTheDocument();
  });

  it("reads In review while an administrator has the submission", async () => {
    vi.mocked(getOrgKyb).mockResolvedValue(
      kyb({ kyb_status: "pending", kyb_submitted_at: "2026-09-13T09:00:00Z" }) as never,
    );

    render(<OrgVerificationPanel />);

    expect(await screen.findByText("In review")).toBeInTheDocument();
    expect(screen.getByText(/we will notify you/i)).toBeInTheDocument();
    expect(screen.queryByText(/awaiting review/i)).not.toBeInTheDocument();
  });

  it("reads Needs changes, not Rejected, because the org can resubmit", async () => {
    vi.mocked(getOrgKyb).mockResolvedValue(
      kyb({ kyb_review_notes: "The certificate is unreadable.", kyb_status: "rejected" }) as never,
    );

    render(<OrgVerificationPanel />);

    expect(await screen.findByText("Needs changes")).toBeInTheDocument();
  });
});
