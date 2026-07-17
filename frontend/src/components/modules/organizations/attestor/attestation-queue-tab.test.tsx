import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { listOrgAttestationsV1OrgsOrgIdAttestationsGet as listQueue } from "@/lib/generated/sdk.gen";
import { AttestationQueueTab } from "./attestation-queue-tab";

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgAttestationsV1OrgsOrgIdAttestationsGet: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
}));

vi.mock("./reassign-reviewer-dialog", () => ({
  ReassignReviewerDialog: () => null,
}));

function item(overrides: Record<string, unknown>) {
  return {
    id: "att-1",
    target_type: "framework",
    target_id: "fw-1",
    target_title: null,
    review_type: "quality",
    status: "in_review",
    outcome: null,
    reviewing_member_id: "m-1",
    reviewing_member_name: "Reviewer One",
    assigned_to_me: true,
    accepted_at: null,
    completion_due_at: null,
    updated_at: "2026-07-16T00:00:00Z",
    unread_answer: false,
    ...overrides,
  };
}

describe("AttestationQueueTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("splits active reviews from completed history across tabs", async () => {
    vi.mocked(listQueue).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          item({ id: "a-active", status: "in_review", target_title: "Active Review" }),
          item({
            id: "a-done",
            status: "released",
            outcome: "verified",
            target_title: "Finished Review",
          }),
        ],
      },
    } as never);

    render(<AttestationQueueTab />);

    // Active tab is the default view.
    expect(await screen.findByText("Active Review")).toBeInTheDocument();
    expect(screen.queryByText("Finished Review")).not.toBeInTheDocument();

    // Switching to History reveals the completed review only.
    fireEvent.click(screen.getByRole("tab", { name: /history/i }));
    expect(await screen.findByText("Finished Review")).toBeInTheDocument();
    expect(screen.queryByText("Active Review")).not.toBeInTheDocument();
  });

  it("shows a submitted report in History, not Active", async () => {
    vi.mocked(listQueue).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          item({
            id: "a-submitted",
            status: "report_submitted",
            outcome: "approved",
            target_title: "Submitted Review",
          }),
        ],
      },
    } as never);

    render(<AttestationQueueTab />);

    // Not in the default Active view.
    await screen.findByRole("tab", { name: /history/i });
    expect(screen.queryByText("Submitted Review")).not.toBeInTheDocument();

    // Appears under History once the reviewer has submitted.
    fireEvent.click(screen.getByRole("tab", { name: /history/i }));
    expect(await screen.findByText("Submitted Review")).toBeInTheDocument();
  });

  it("flags an active review that has an unread clarification answer", async () => {
    vi.mocked(listQueue).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          item({ id: "a-unread", status: "in_review", unread_answer: true, target_title: "Needs Attention" }),
        ],
      },
    } as never);

    render(<AttestationQueueTab />);

    expect(await screen.findByText("Answer received")).toBeInTheDocument();
  });
});
