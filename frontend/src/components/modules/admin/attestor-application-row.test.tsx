import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { rejectOrgAttestor } from "@/lib/generated/sdk.gen";
import { AttestorApplicationRow } from "./attestor-application-row";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  rejectOrgAttestor: vi.fn(),
}));

const submittedApplication = {
  id: "app-1",
  status: "submitted",
  credentials_summary: "Ten years in compliance.",
  professional_references: null,
  jurisdictions: ["US"],
  admin_feedback: null,
} as never;

describe("AttestorApplicationRow", () => {
  it("rejects inline with feedback and no 2FA", async () => {
    vi.mocked(rejectOrgAttestor).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);
    const onRejected = vi.fn();

    render(
      <AttestorApplicationRow
        application={submittedApplication}
        onRejected={onRejected}
      />,
    );

    // Reject disabled until feedback is entered.
    expect(screen.getByRole("button", { name: /Reject/i })).toBeDisabled();

    fireEvent.change(
      screen.getByPlaceholderText(/Why is this application rejected/i),
      { target: { value: "Insufficient references." } },
    );
    fireEvent.click(screen.getByRole("button", { name: /Reject/i }));

    await waitFor(() => {
      expect(rejectOrgAttestor).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { application_id: "app-1" },
          body: { feedback: "Insufficient references." },
        }),
      );
    });
    expect(onRejected).toHaveBeenCalledWith("app-1");
  });
});
