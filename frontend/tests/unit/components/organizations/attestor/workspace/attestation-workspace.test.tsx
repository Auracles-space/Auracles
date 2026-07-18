import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

describe("AttestationWorkspace", () => {
  beforeEach(() => vi.clearAllMocks());

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
});
