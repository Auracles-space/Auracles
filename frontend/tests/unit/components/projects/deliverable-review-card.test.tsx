import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeliverableReviewCard } from "@/components/modules/projects/deliverable-review-card";
import {
  approveOrgDeliverable,
  listDeliverables,
  requestOrgDeliverableRevision,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/form-client")>("@/lib/auth/form-client");
  return {
    ...actual,
    configureBrowserClient: vi.fn(),
    getAccessTokenHeaders: vi.fn(() => ({})),
  };
});

vi.mock("@/lib/generated/sdk.gen", () => ({
  approveDeliverable: vi.fn(),
  approveOrgDeliverable: vi.fn(),
  downloadDeliverableFiles: vi.fn(),
  listDeliverables: vi.fn(),
  requestDeliverableRevision: vi.fn(),
  requestOrgDeliverableRevision: vi.fn(),
}));

const approveOrgDeliverableMock = vi.mocked(approveOrgDeliverable);
const listDeliverablesMock = vi.mocked(listDeliverables);

describe("DeliverableReviewCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("routes approval through approveOrgDeliverable in org mode", async () => {
    listDeliverablesMock.mockResolvedValue({
      data: {
        deliverables: [
          {
            id: "deliv-1",
            milestone_id: "milestone-1",
            project_id: "project-1",
            contributor_id: "contrib-1",
            created_at: "2026-06-20T10:00:00Z",
            scan_status: "visible",
            status: "submitted",
            description: "Done",
            file_keys: ["file-1"],
          },
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    approveOrgDeliverableMock.mockResolvedValue({
      data: {},
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    const onChanged = vi.fn();

    render(
      <DeliverableReviewCard
        isOperator={true}
        milestoneId="milestone-1"
        milestoneStatus="submitted"
        mode={{ kind: "org", orgId: "org-1" }}
        onChanged={onChanged}
        projectId="project-1"
      />
    );

    // Wait for load
    await waitFor(() => {
      expect(screen.getByText("Done")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /approve and release escrow/i }));

    await waitFor(() => expect(approveOrgDeliverableMock).toHaveBeenCalledTimes(1));
    expect(approveOrgDeliverableMock).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1", project_id: "project-1", deliverable_id: "deliv-1" },
      })
    );
  });

  it("polls while the file is scanning and updates when the scan finishes", async () => {
    const scanning = {
      id: "deliv-1",
      milestone_id: "milestone-1",
      project_id: "project-1",
      contributor_id: "contrib-1",
      created_at: "2026-06-20T10:00:00Z",
      scan_status: "pending_scan",
      status: "submitted",
      description: "Done",
      file_keys: ["file-1"],
    };
    const okResponse = new Response(null, { status: 200 });
    listDeliverablesMock
      .mockResolvedValueOnce({
        data: { deliverables: [scanning] },
        error: undefined,
        response: okResponse,
      } as never)
      .mockResolvedValue({
        data: {
          deliverables: [{ ...scanning, scan_status: "visible" }],
        },
        error: undefined,
        response: okResponse,
      } as never);

    vi.useFakeTimers();
    try {
      render(
        <DeliverableReviewCard
          isOperator={false}
          milestoneId="milestone-1"
          milestoneStatus="submitted"
          onChanged={vi.fn()}
          projectId="project-1"
        />,
      );

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText(/scanning/i)).toBeInTheDocument();
      expect(listDeliverablesMock).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(listDeliverablesMock.mock.calls.length).toBeGreaterThan(1);
      expect(screen.getByText(/scanned/i)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("routes a revision request through the organization endpoint", async () => {
    listDeliverablesMock.mockResolvedValue({
      data: {
        deliverables: [
          {
            id: "deliv-1",
            milestone_id: "milestone-1",
            project_id: "project-1",
            contributor_id: "contrib-1",
            created_at: "2026-06-20T10:00:00Z",
            scan_status: "visible",
            status: "submitted",
            description: "Done",
            file_keys: ["file-1"],
          },
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    vi.mocked(requestOrgDeliverableRevision).mockResolvedValue({
      data: {},
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(
      <DeliverableReviewCard
        isOperator={true}
        milestoneId="milestone-1"
        milestoneStatus="submitted"
        mode={{ kind: "org", orgId: "org-1" }}
        onChanged={vi.fn()}
        projectId="project-1"
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /request changes/i }));
    fireEvent.change(
      screen.getByPlaceholderText(/what needs to change/i),
      { target: { value: "Please revise the controls." } },
    );
    fireEvent.click(screen.getByRole("button", { name: /send request/i }));

    await waitFor(() => expect(requestOrgDeliverableRevision).toHaveBeenCalledTimes(1));
    expect(requestOrgDeliverableRevision).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { revision_notes: "Please revise the controls." },
        path: {
          deliverable_id: "deliv-1",
          milestone_id: "milestone-1",
          org_id: "org-1",
          project_id: "project-1",
        },
      }),
    );
  });
});
