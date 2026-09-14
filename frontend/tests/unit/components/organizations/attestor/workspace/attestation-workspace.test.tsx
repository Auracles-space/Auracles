import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AttestationWorkspace } from "@/components/modules/organizations/attestor/workspace/attestation-workspace";
import { getAttestation, listOrgAttestations } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "member", memberId: "mem-1" }),
}));
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), refresh: vi.fn() }))
}));
vi.mock("@/components/modules/organizations/attestor/workspace/framework-files-panel", () => ({
  FrameworkFilesPanel: () => <div>Framework files</div>,
}));
vi.mock("@/components/modules/organizations/attestor/workspace/rubric-panel", () => ({
  RubricPanel: () => <div>Rubric</div>,
}));
vi.mock("@/components/modules/organizations/attestor/workspace/annotations-panel", () => ({
  AnnotationsPanel: () => <div>Annotations</div>,
}));
vi.mock("@/components/modules/organizations/attestor/workspace/clarifications-panel", () => ({
  ClarificationsPanel: () => <div>Clarifications</div>,
}));
vi.mock("@/components/modules/organizations/attestor/workspace/report-panel", () => ({
  ReportPanel: () => <div>Report</div>,
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  getAttestation: vi.fn(),
  listOrgAttestations: vi.fn(),
  startAttestationReview: vi.fn(),
  giveAttestationConsent: vi.fn(),
  ackAttestationContent: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

function queue(overrides: Record<string, unknown> = {}) {
  return ok({
    attestations: [
      {
        id: "att-1",
        status: "in_review",
        assigned_to_me: true,
        target_title: "Framework One",
        reviewing_member_name: "Reviewing Member",
        completion_due_at: null,
        ...overrides,
      },
    ],
  }) as never;
}

describe("AttestationWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-09-14T12:00:00Z"));
  });

  afterEach(() => vi.useRealTimers());

  it("offers Start review to the assigned reviewing member before review starts", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({
        id: "att-1",
        status: "accepted",
        target_type: "framework",
        review_type: "quality",
      }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(
      ok({
        attestations: [
          {
            id: "att-1",
            status: "accepted",
            assigned_to_me: true,
            target_title: "Framework One",
            reviewing_member_name: "Reviewing Member",
          },
        ],
      }) as never,
    );
    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);
    const startButton = await screen.findByRole("button", {
      name: /start review/i,
    });
    expect(startButton).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(startButton).toBeEnabled();
  });

  it("is read-only for an owner who is not the reviewing member", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({
        id: "att-1",
        status: "in_review",
        target_type: "framework",
        review_type: "quality",
      }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(
      ok({
        attestations: [
          {
            id: "att-1",
            status: "in_review",
            assigned_to_me: false,
            target_title: "Framework One",
            reviewing_member_name: "Another Reviewer",
          },
        ],
      }) as never,
    );
    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);
    await screen.findByText("Framework One");
    expect(screen.getByText("Read-only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start review/i })).toBeNull();
  });

  it("names the status in the attestor's vocabulary and shows the deadline", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({
        id: "att-1",
        status: "in_review",
        target_type: "framework",
        review_type: "quality",
        completion_due_at: "2026-09-18T00:00:00Z",
      }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(queue());

    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);

    expect(await screen.findByText("In review")).toBeInTheDocument();
    expect(screen.getByText("Due 18 Sep 2026")).toBeInTheDocument();
  });

  it("shows the dispute window while the report sits with the requestor", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({
        id: "att-1",
        status: "report_submitted",
        target_type: "framework",
        review_type: "quality",
        dispute_window_ends_at: "2026-09-21T00:00:00Z",
      }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(
      queue({ status: "report_submitted" }),
    );

    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);

    expect(await screen.findByText("Submitted")).toBeInTheDocument();
    expect(
      screen.getByText("Dispute window ends 21 Sep 2026"),
    ).toBeInTheDocument();
  });

  it("summarises what the requestor asked for", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({
        id: "att-1",
        status: "in_review",
        target_type: "framework",
        review_type: "quality",
        brief: {
          what_it_does: "Scores supplier risk.",
          use_case: "Procurement teams onboarding vendors.",
          desired_outcome: "Confirm the scoring model is defensible.",
        },
      }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(queue());

    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);

    expect(
      await screen.findByText("What the requestor asked for"),
    ).toBeInTheDocument();
    expect(screen.getByText("Scores supplier risk.")).toBeInTheDocument();
    expect(
      screen.getByText("Procurement teams onboarding vendors."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Confirm the scoring model is defensible."),
    ).toBeInTheDocument();
  });

  it("shows the dispute reason, category and decision deadline", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({
        id: "att-1",
        status: "disputed",
        target_type: "framework",
        review_type: "quality",
        dispute: {
          id: "dis-1",
          status: "open",
          category: "material_inaccuracy",
          reason: "Section 4 misreads our retention policy.",
          created_at: "2026-09-12T00:00:00Z",
          resolution_due_at: "2026-09-19T00:00:00Z",
        },
      }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(queue({ status: "disputed" }));

    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);

    expect(await screen.findByText("Dispute")).toBeInTheDocument();
    expect(screen.getByText("Material Inaccuracy")).toBeInTheDocument();
    expect(
      screen.getByText("Section 4 misreads our retention policy."),
    ).toBeInTheDocument();
    expect(screen.getByText("Decision due 19 Sep 2026")).toBeInTheDocument();
  });

  it("shows the admin's revision notes and the new deadline", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({
        id: "att-1",
        status: "revision_requested",
        target_type: "framework",
        review_type: "quality",
        completion_due_at: "2026-09-25T00:00:00Z",
        dispute: {
          id: "dis-1",
          status: "resolved",
          category: "material_inaccuracy",
          reason: "Section 4 misreads our retention policy.",
          outcome: "upheld_revise",
          resolution_notes: "Re-check section 4 against the policy document.",
          resolved_at: "2026-09-14T00:00:00Z",
          created_at: "2026-09-12T00:00:00Z",
        },
      }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(
      queue({ status: "revision_requested", completion_due_at: "2026-09-25T00:00:00Z" }),
    );

    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);

    // The status pill carries the same words, so match the card's heading.
    expect(
      await screen.findByRole("heading", { name: "Revision requested" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Re-check section 4 against the policy document."),
    ).toBeInTheDocument();
    expect(screen.getByText("New due date 25 Sep 2026")).toBeInTheDocument();
    // The header still carries the deadline itself.
    expect(screen.getByText("Due 25 Sep 2026")).toBeInTheDocument();
  });
});
