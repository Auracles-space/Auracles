import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { getAdminAttestationDetail } from "@/lib/generated/sdk.gen";
import { AttestationDetailModal } from "./attestation-detail-modal";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getAdminAttestationDetail: vi.fn(),
}));

describe("AttestationDetailModal", () => {
  it("shows the status and the offer's org", async () => {
    vi.mocked(getAdminAttestationDetail).mockResolvedValue({
      response: { ok: true },
      data: {
        attestation: {
          id: "att-1",
          target_type: "framework",
          target_id: "fw-1",
          requestor_id: "user-1",
          attestor_org_id: null,
          status: "offered",
          outcome: null,
          review_type: "quality",
          requested_specializations: [],
          requested_jurisdictions: [],
          fee_amount: "500.00",
          currency: "USD",
          escrow_id: "esc-1",
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
        offers: [
          {
            org_id: "org-1",
            org_name: "Acme Advisory",
            status: "offered",
            cohort_index: 0,
            offered_at: "2026-07-16T01:00:00Z",
            expires_at: "2026-07-18T01:00:00Z",
            responded_at: null,
          },
        ],
      },
    } as never);

    render(
      <AttestationDetailModal attestationId="att-1" onClose={vi.fn()} />,
    );

    expect(await screen.findByText("Acme Advisory")).toBeInTheDocument();
    expect(screen.getByText("Offers (1)")).toBeInTheDocument();
    expect(getAdminAttestationDetail).toHaveBeenCalledWith(
      expect.objectContaining({ path: { attestation_id: "att-1" } }),
    );
  });

  it("names the admin step in the admin's own vocabulary", async () => {
    vi.mocked(getAdminAttestationDetail).mockResolvedValue({
      response: { ok: true },
      data: {
        attestation: {
          id: "att-2",
          target_type: "framework",
          target_id: "fw-1",
          requestor_id: "user-1",
          attestor_org_id: null,
          status: "needs_admin",
          outcome: null,
          review_type: "quality",
          requested_specializations: [],
          requested_jurisdictions: [],
          fee_amount: "500.00",
          currency: "NGN",
          escrow_id: "esc-1",
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
        offers: [],
      },
    } as never);

    render(<AttestationDetailModal attestationId="att-2" onClose={vi.fn()} />);

    expect(await screen.findByText("Needs admin")).toBeInTheDocument();
    expect(screen.queryByText("Finding attestor")).toBeNull();
  });

  it("shows why an org declined its offer", async () => {
    vi.mocked(getAdminAttestationDetail).mockResolvedValue({
      response: { ok: true },
      data: {
        attestation: {
          id: "att-3",
          target_type: "framework",
          target_id: "fw-1",
          requestor_id: "user-1",
          attestor_org_id: null,
          status: "matching",
          outcome: null,
          review_type: "quality",
          requested_specializations: [],
          requested_jurisdictions: [],
          fee_amount: "500.00",
          currency: "NGN",
          escrow_id: "esc-1",
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
        offers: [
          {
            org_id: "org-1",
            org_name: "Acme Advisory",
            status: "declined",
            cohort_index: 0,
            offered_at: "2026-07-16T01:00:00Z",
            expires_at: "2026-07-18T01:00:00Z",
            responded_at: "2026-07-17T01:00:00Z",
            decline_reason: "Outside our jurisdiction",
          },
        ],
      },
    } as never);

    render(<AttestationDetailModal attestationId="att-3" onClose={vi.fn()} />);

    expect(
      await screen.findByText("Reason: Outside our jurisdiction"),
    ).toBeInTheDocument();
    expect(screen.getByText("Declined")).toBeInTheDocument();
  });

  it("shows the brief, report, scores, annotations and questions to judge a dispute", async () => {
    vi.mocked(getAdminAttestationDetail).mockResolvedValue({
      response: { ok: true },
      data: {
        attestation: {
          id: "att-3",
          target_type: "framework",
          target_id: "fw-1",
          target_title: "Seed-Stage Playbook",
          requestor_id: "user-1",
          attestor_org_id: "org-1",
          attestor_org_name: "Ikeji Advisory",
          status: "disputed",
          outcome: "conditional",
          review_type: "compliance",
          brief: { what_it_does: "Seed diligence for Nigerian VC teams." },
          requested_specializations: [],
          requested_jurisdictions: [],
          fee_amount: "350000.00",
          currency: "NGN",
          escrow_id: "esc-1",
          created_at: "2026-09-15T00:00:00Z",
          updated_at: "2026-09-15T00:00:00Z",
        },
        offers: [],
        report: {
          outcome: "conditional",
          summary: "Broadly aligned with Nigerian requirements.",
          scope: "Reviewed against CAC and NDPA 2023.",
          conditions: "Add FIRS and PenCom checks.",
          rubric: [
            { dimension_key: "regulatory_alignment", label: "Regulatory Alignment", score: 3, comment: "Cites NDPR 2019." },
          ],
          annotations: [
            { id: "an-1", artifact_id: null, location_label: "Section 3", quoted_excerpt: null, annotation_type: "concern", comment: "Check the PSC register." },
          ],
          clarifications: [
            { id: "cl-1", question: "Does FX cover 2024?", response: "Only pre-2024.", status: "answered" },
          ],
        },
      },
    } as never);

    render(<AttestationDetailModal attestationId="att-3" onClose={vi.fn()} />);

    expect(await screen.findByText("Seed-Stage Playbook")).toBeInTheDocument();
    expect(screen.getByText("Seed diligence for Nigerian VC teams.")).toBeInTheDocument();
    expect(screen.getByText("Broadly aligned with Nigerian requirements.")).toBeInTheDocument();
    expect(screen.getByText("Add FIRS and PenCom checks.")).toBeInTheDocument();
    expect(screen.getByText("Regulatory Alignment")).toBeInTheDocument();
    expect(screen.getByText("Cites NDPR 2019.")).toBeInTheDocument();
    expect(screen.getByText("Check the PSC register.")).toBeInTheDocument();
    expect(screen.getByText("Does FX cover 2024?")).toBeInTheDocument();
    expect(screen.getByText("Only pre-2024.")).toBeInTheDocument();
  });
});
