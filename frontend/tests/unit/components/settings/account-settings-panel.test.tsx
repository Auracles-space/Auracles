/**
 * Unit coverage for the account settings panel.
 *
 * Verifies email-change behavior plus the GDPR delete-account flow that
 * replaces the legacy deactivation action.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountSettingsPanel } from "@/components/modules/settings/account-settings-panel";
import {
  cancelAccountDeletion,
  getAccountDeletionStatus,
  requestAccountDeletion,
  requestEmailChange,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  cancelAccountDeletion: vi.fn(),
  getAccountDeletionStatus: vi.fn(),
  requestAccountDeletion: vi.fn(),
  requestEmailChange: vi.fn(),
}));

const emptyDeletionStatus = {
  blocked_reasons: [],
  completed_at: null,
  id: null,
  requested_at: null,
  scheduled_for: null,
  status: null,
};

describe("AccountSettingsPanel", () => {
  beforeEach(() => {
    vi.mocked(cancelAccountDeletion).mockReset();
    vi.mocked(getAccountDeletionStatus).mockReset();
    vi.mocked(requestAccountDeletion).mockReset();
    vi.mocked(requestEmailChange).mockReset();
    vi.mocked(getAccountDeletionStatus).mockResolvedValue({
      data: emptyDeletionStatus,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
  });

  it("requires a 2FA code before requesting an email change", async () => {
    render(<AccountSettingsPanel />);

    fireEvent.change(screen.getByLabelText(/new email/i), {
      target: { value: "next@auracles.space" },
    });
    fireEvent.click(screen.getByRole("button", { name: /request email change/i }));

    expect(await screen.findByText(/enter a 2fa code/i)).toBeInTheDocument();
    expect(requestEmailChange).not.toHaveBeenCalled();
  });

  it("submits an email-change request through the generated client", async () => {
    vi.mocked(requestEmailChange).mockResolvedValue({
      data: { message: "Email change verification sent." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AccountSettingsPanel />);

    fireEvent.change(screen.getByLabelText(/new email/i), {
      target: { value: "next@auracles.space" },
    });
    fireEvent.change(screen.getByLabelText(/^2fa code$/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /request email change/i }));

    await waitFor(() => {
      expect(requestEmailChange).toHaveBeenCalledWith({
        body: { new_email: "next@auracles.space", totp_code: "123456" },
        headers: { Authorization: "Bearer access-token" },
      });
    });
  });

  it("submits a delete-account request and shows blocked reasons from the GDPR endpoint", async () => {
    vi.mocked(requestAccountDeletion).mockResolvedValue({
      data: undefined,
      error: {
        blocked_reasons: [
          {
            code: "held_escrow",
            count: 1,
            message: "Resolve held escrow before deleting your account.",
          },
        ],
        completed_at: null,
        id: "request-1",
        requested_at: "2026-06-12T09:00:00Z",
        scheduled_for: null,
        status: "blocked",
      },
      response: new Response(null, { status: 409 }),
    });

    render(<AccountSettingsPanel />);

    expect(screen.queryByText(/deactivate account/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/current password/i), {
      target: { value: "CorrectHorse9" },
    });
    fireEvent.change(screen.getByLabelText(/confirmation code/i), {
      target: { value: "654321" },
    });
    fireEvent.click(screen.getByRole("button", { name: /delete account/i }));

    await waitFor(() => {
      expect(requestAccountDeletion).toHaveBeenCalledWith({
        body: { password: "CorrectHorse9", totp_code: "654321" },
        headers: { Authorization: "Bearer access-token" },
      });
    });

    expect(
      await screen.findByText(/resolve held escrow before deleting your account/i),
    ).toBeInTheDocument();
  });

  it("loads a scheduled deletion request and lets the user cancel it", async () => {
    vi.mocked(getAccountDeletionStatus).mockResolvedValue({
      data: {
        blocked_reasons: [],
        completed_at: null,
        id: "request-2",
        requested_at: "2026-06-12T09:00:00Z",
        scheduled_for: "2026-06-26T09:00:00Z",
        status: "scheduled",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(cancelAccountDeletion).mockResolvedValue({
      data: {
        blocked_reasons: [],
        completed_at: null,
        id: "request-2",
        requested_at: "2026-06-12T09:00:00Z",
        scheduled_for: null,
        status: "cancelled",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AccountSettingsPanel />);

    const deletionSection = await screen.findByRole("region", {
      name: /delete account/i,
    });

    expect(
      within(deletionSection).getByText(/your account is scheduled for deletion/i),
    ).toBeInTheDocument();

    fireEvent.click(
      within(deletionSection).getByRole("button", { name: /cancel deletion request/i }),
    );

    await waitFor(() => {
      expect(cancelAccountDeletion).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer access-token" },
      });
    });

    expect(
      await within(deletionSection).findByText(
        /deletion request cancelled\. your account remains active\./i,
      ),
    ).toBeInTheDocument();
  });
});
