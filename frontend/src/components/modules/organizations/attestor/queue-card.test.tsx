import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QueueCard } from "./queue-card";

function attestation(status: string) {
  return {
    id: "att-1",
    status,
    target_type: "framework",
    target_title: "Seed-Stage Playbook",
    review_type: "compliance",
    reviewing_member_name: "Ada Okafor",
    completion_due_at: null,
    outcome: null,
    unread_answer: false,
    updated_at: "2026-09-15T12:00:00Z",
  } as never;
}

describe("QueueCard reassignment", () => {
  it("offers Reassign before the reviewer has started", () => {
    render(
      <QueueCard
        active
        attestation={attestation("accepted")}
        isAdmin
        onOpen={vi.fn()}
        onReassign={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Reassign" })).toBeInTheDocument();
  });

  it.each(["in_review", "report_submitted", "disputed"])(
    "hides Reassign once the review is %s",
    (status) => {
      // The server refuses reassignment after review starts ("reassignment
      // requires an admin"), so the button only led to an error.
      render(
        <QueueCard
          active
          attestation={attestation(status)}
          isAdmin
          onOpen={vi.fn()}
          onReassign={vi.fn()}
        />,
      );

      expect(screen.queryByRole("button", { name: "Reassign" })).toBeNull();
    },
  );
});
