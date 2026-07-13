/**
 * Unit coverage for the Deliverable submission form.
 *
 * Verifies the success path surfaces a toast (the form unmounts on submit, so
 * the confirmation lands off-screen in the milestone timeline) and hands the
 * created Deliverable back to the workspace.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeliverableSubmitForm } from "@/components/modules/projects/deliverable-submit-form";
import { ToastProvider } from "@/components/ui/toast";
import {
  createWorkspaceUploadSession,
  submitDeliverable,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createWorkspaceUploadSession: vi.fn(),
  submitDeliverable: vi.fn(),
}));

describe("DeliverableSubmitForm", () => {
  beforeEach(() => {
    vi.mocked(createWorkspaceUploadSession).mockReset();
    vi.mocked(submitDeliverable).mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );
  });

  it("toasts and returns the deliverable on a successful submit", async () => {
    vi.mocked(createWorkspaceUploadSession).mockResolvedValue({
      data: { url: "https://s3.example/upload", fields: {}, s3_key: "key-1" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    vi.mocked(submitDeliverable).mockResolvedValue({
      data: { id: "del-1" },
      error: undefined,
      response: new Response(null, { status: 201 }),
    } as never);
    const onSubmitted = vi.fn();

    const { container } = render(
      <ToastProvider>
        <DeliverableSubmitForm
          milestoneId="ms-1"
          onCancel={vi.fn()}
          onSubmitted={onSubmitted}
          projectId="proj-1"
        />
      </ToastProvider>,
    );

    fireEvent.change(screen.getByPlaceholderText(/final procurement playbook/i), {
      target: { value: "Procurement playbook" },
    });
    fireEvent.change(
      screen.getByPlaceholderText(/summarize the work completed/i),
      { target: { value: "Delivered the full playbook." } },
    );
    const fileInput = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["data"], "playbook.pdf", { type: "application/pdf" })],
      },
    });

    fireEvent.click(
      screen.getByRole("button", { name: /^submit deliverable$/i }),
    );

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(
      await screen.findByText(/deliverable submitted/i),
    ).toBeInTheDocument();
  });
});
