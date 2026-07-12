import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MilestoneDisputePanel } from "@/components/modules/projects/milestone-dispute-panel";
import { createDispute } from "@/lib/generated/sdk.gen";
import type { DisputeResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/form-client")>(
    "@/lib/auth/form-client",
  );
  return {
    ...actual,
    configureBrowserClient: vi.fn(),
    getAccessTokenHeaders: vi.fn(() => ({})),
  };
});

vi.mock("@/lib/generated/sdk.gen", () => ({
  createDispute: vi.fn(),
}));

const createDisputeMock = vi.mocked(createDispute);

function dispute(overrides: Partial<DisputeResponse> = {}): DisputeResponse {
  return {
    admin_id: null,
    created_at: "2026-06-21T10:00:00Z",
    escalated_at: null,
    id: "dispute-1",
    milestone_id: "milestone-1",
    project_id: "project-1",
    raised_by_side: null,
    reason: "Deliverable does not match the agreed scope.",
    refund_amount: null,
    release_amount: null,
    resolution_notes: null,
    resolution_type: null,
    resolved_at: null,
    status: "open",
    ...overrides,
  };
}

beforeEach(() => {
  createDisputeMock.mockReset();
});

describe("MilestoneDisputePanel", () => {
  it("shows an existing dispute's status and reason", () => {
    render(
      <MilestoneDisputePanel
        canRaise={false}
        dispute={dispute()}
        milestoneId="milestone-1"
        milestoneStatus="disputed"
        onRaised={vi.fn()}
        projectId="project-1"
      />,
    );

    expect(screen.getByText(/open/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Deliverable does not match the agreed scope/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /raise dispute/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the resolution outcome once resolved", () => {
    render(
      <MilestoneDisputePanel
        canRaise={false}
        dispute={dispute({
          status: "resolved",
          resolution_type: "refund",
          resolution_notes: "Work incomplete; refunded operator.",
        })}
        milestoneId="milestone-1"
        milestoneStatus="cancelled"
        onRaised={vi.fn()}
        projectId="project-1"
      />,
    );

    expect(screen.getByText(/refund/i)).toBeInTheDocument();
    expect(screen.getByText(/Work incomplete/i)).toBeInTheDocument();
  });

  it("lets a member raise a dispute on a funded milestone", async () => {
    createDisputeMock.mockResolvedValue({
      data: dispute(),
      error: undefined,
      response: new Response(null, { status: 201 }),
    } as never);
    const onRaised = vi.fn();

    render(
      <MilestoneDisputePanel
        canRaise
        dispute={null}
        milestoneId="milestone-1"
        milestoneStatus="funded"
        onRaised={onRaised}
        projectId="project-1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /raise dispute/i }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Deliverable does not match the agreed scope." },
    });
    fireEvent.click(screen.getByRole("button", { name: /submit dispute/i }));

    await waitFor(() => expect(createDisputeMock).toHaveBeenCalledTimes(1));
    expect(createDisputeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        body: {
          milestone_id: "milestone-1",
          reason: "Deliverable does not match the agreed scope.",
        },
        path: { project_id: "project-1" },
      }),
    );
    await waitFor(() => expect(onRaised).toHaveBeenCalledTimes(1));
  });

  it("blocks a too-short reason without calling the API", () => {
    const onRaised = vi.fn();
    render(
      <MilestoneDisputePanel
        canRaise
        dispute={null}
        milestoneId="milestone-1"
        milestoneStatus="submitted"
        onRaised={onRaised}
        projectId="project-1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /raise dispute/i }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "too short" },
    });
    fireEvent.click(screen.getByRole("button", { name: /submit dispute/i }));

    expect(createDisputeMock).not.toHaveBeenCalled();
    expect(onRaised).not.toHaveBeenCalled();
    expect(screen.getByText(/at least 10 characters/i)).toBeInTheDocument();
  });

  it("does not offer to raise a dispute on an unfunded milestone", () => {
    render(
      <MilestoneDisputePanel
        canRaise
        dispute={null}
        milestoneId="milestone-1"
        milestoneStatus="pending"
        onRaised={vi.fn()}
        projectId="project-1"
      />,
    );

    expect(
      screen.queryByRole("button", { name: /raise dispute/i }),
    ).not.toBeInTheDocument();
  });
});
