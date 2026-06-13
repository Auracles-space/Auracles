/**
 * Unit coverage for the admin moderation panel.
 *
 * Verifies that the unified moderation queue renders different signal types
 * and flags when follow-up requires a Contributor-side action.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminModerationPanel } from "@/components/modules/admin/admin-moderation-panel";
import { listModerationQueueV1AdminModerationQueueGet } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listModerationQueueV1AdminModerationQueueGet: vi.fn(),
}));

describe("AdminModerationPanel", () => {
  beforeEach(() => {
    vi.mocked(listModerationQueueV1AdminModerationQueueGet).mockReset();
    vi.mocked(listModerationQueueV1AdminModerationQueueGet).mockResolvedValue({
      data: {
        items: [
          {
            action_links: [
              {
                actor_role: "admin",
                method: "POST",
                path: "/v1/admin/frameworks/framework-1/suspend",
                rel: "suspend_framework",
              },
            ],
            artifact_id: "artifact-1",
            artifact_name: "blocked-playbook.pdf",
            contributor_id: "contributor-1",
            contributor_name: "Ada Contributor",
            details: {
              internal_jaccard: "0.9500",
            },
            framework_id: "framework-1",
            framework_title: "Blocked Similarity Framework",
            queue_type: "near_duplicate_block",
            signal_at: "2026-06-12T12:00:00Z",
            signal_id: "signal-1",
          },
          {
            action_links: [
              {
                actor_role: "contributor",
                method: "POST",
                path: "/v1/frameworks/framework-2/artifacts/artifact-2/accept-redaction",
                rel: "accept_redaction",
              },
            ],
            artifact_id: "artifact-2",
            artifact_name: "pii-playbook.pdf",
            contributor_id: "contributor-2",
            contributor_name: "Bayo Contributor",
            details: {
              pii_types_found: ["email"],
              redaction_available: true,
            },
            framework_id: "framework-2",
            framework_title: "PII Framework",
            queue_type: "pii_review",
            signal_at: "2026-06-12T13:00:00Z",
            signal_id: "signal-2",
          },
        ],
        page: 1,
        page_size: 20,
        total: 2,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
  });

  it("renders queue rows and can request a different queue filter", async () => {
    render(<AdminModerationPanel />);

    expect(
      await screen.findByRole("heading", { name: /moderation queue/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Blocked Similarity Framework")).toBeInTheDocument();
    expect(screen.getByText("PII Framework")).toBeInTheDocument();
    expect(screen.getByText("Contributor follow-up required")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/queue type/i), {
      target: { value: "pii_review" },
    });

    await waitFor(() => {
      expect(listModerationQueueV1AdminModerationQueueGet).toHaveBeenLastCalledWith({
        headers: { Authorization: "Bearer admin-token" },
        query: {
          page: 1,
          page_size: 20,
          type: "pii_review",
        },
      });
    });
  });
});
