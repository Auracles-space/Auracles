import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-09-14T12:00:00Z"));
  });

  afterEach(() => vi.useRealTimers());

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

  it("reads a submitted report in the attestor's own vocabulary", async () => {
    vi.mocked(listQueue).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          item({ status: "report_submitted", target_title: "Submitted Review" }),
        ],
      },
    } as never);

    render(<AttestationQueueTab />);

    fireEvent.click(await screen.findByRole("tab", { name: /history/i }));
    expect(await screen.findByText("Submitted")).toBeInTheDocument();
    expect(screen.queryByText("Report ready")).toBeNull();
  });

  it("shows the completion deadline on an active review", async () => {
    vi.mocked(listQueue).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          item({
            status: "in_review",
            target_title: "Dated Review",
            completion_due_at: "2026-09-20T00:00:00Z",
          }),
        ],
      },
    } as never);

    render(<AttestationQueueTab />);

    expect(await screen.findByText("Due 20 Sep 2026")).toBeInTheDocument();
    expect(screen.queryByText(/Overdue/)).toBeNull();
  });

  it("flags a review whose deadline has passed", async () => {
    vi.mocked(listQueue).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          item({
            status: "in_review",
            target_title: "Late Review",
            completion_due_at: "2026-09-10T00:00:00Z",
          }),
        ],
      },
    } as never);

    render(<AttestationQueueTab />);

    expect(await screen.findByText("Due 10 Sep 2026")).toBeInTheDocument();
    expect(screen.getByText(/Overdue/)).toHaveClass("text-error");
  });

  it("does not call a finished review overdue", async () => {
    vi.mocked(listQueue).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          item({
            status: "released",
            target_title: "Old Review",
            completion_due_at: "2026-09-10T00:00:00Z",
          }),
        ],
      },
    } as never);

    render(<AttestationQueueTab />);

    fireEvent.click(await screen.findByRole("tab", { name: /history/i }));
    await screen.findByText("Old Review");
    expect(screen.queryByText(/Overdue/)).toBeNull();
  });

  it("files a withdrawn request under History", async () => {
    vi.mocked(listQueue).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          item({ status: "cancelled", target_title: "Withdrawn Request" }),
        ],
      },
    } as never);

    render(<AttestationQueueTab />);

    fireEvent.click(await screen.findByRole("tab", { name: /history/i }));
    expect(await screen.findByText("Withdrawn Request")).toBeInTheDocument();
    expect(screen.getByText("Withdrawn")).toBeInTheDocument();
  });
});
