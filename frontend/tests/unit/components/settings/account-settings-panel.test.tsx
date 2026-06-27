/**
 * Unit coverage for the account settings panel.
 *
 * Verifies email-change behavior plus GDPR data-export and delete-account
 * controls on the authenticated account settings page.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountSettingsPanel } from "@/components/modules/settings/account-settings-panel";
import {
  cancelAccountDeletion,
  downloadDataExportV1GdprExportsExportRequestIdDownloadGet,
  getAccountDeletionStatus,
  getCurrentUser,
  getLatestDataExportStatusV1GdprExportsLatestGet,
  requestAccountDeletion,
  requestDataExportV1GdprExportsPost,
  requestEmailChange,
  totpStatus,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
  getAccessToken: () => "access-token",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  cancelAccountDeletion: vi.fn(),
  downloadDataExportV1GdprExportsExportRequestIdDownloadGet: vi.fn(),
  getAccountDeletionStatus: vi.fn(),
  getCurrentUser: vi.fn(),
  getLatestDataExportStatusV1GdprExportsLatestGet: vi.fn(),
  requestAccountDeletion: vi.fn(),
  requestDataExportV1GdprExportsPost: vi.fn(),
  requestEmailChange: vi.fn(),
  totpStatus: vi.fn(),
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
    vi.mocked(downloadDataExportV1GdprExportsExportRequestIdDownloadGet).mockReset();
    vi.mocked(getAccountDeletionStatus).mockReset();
    vi.mocked(getLatestDataExportStatusV1GdprExportsLatestGet).mockReset();
    vi.mocked(requestAccountDeletion).mockReset();
    vi.mocked(requestDataExportV1GdprExportsPost).mockReset();
    vi.mocked(requestEmailChange).mockReset();
    vi.mocked(getAccountDeletionStatus).mockResolvedValue({
      data: emptyDeletionStatus,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(getLatestDataExportStatusV1GdprExportsLatestGet).mockResolvedValue({
      data: undefined,
      error: { detail: "No data export request found." },
      response: new Response(null, { status: 404 }),
    });
    vi.mocked(totpStatus).mockReset();
    vi.mocked(totpStatus).mockResolvedValue({
      data: { totp_enabled: false },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(getCurrentUser).mockReset();
    vi.mocked(getCurrentUser).mockResolvedValue({
      data: { has_password: true },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    vi.stubGlobal("location", {
      assign: vi.fn(),
    });
  });

  it("hides the deletion confirmation code field when 2FA is disabled", async () => {
    render(<AccountSettingsPanel />);

    // Password is required for everyone; the 2FA code field must not appear for
    // accounts without 2FA enabled.
    await screen.findByLabelText(/current password/i);
    expect(
      screen.queryByLabelText(/confirmation code/i),
    ).not.toBeInTheDocument();
  });

  it("shows the deletion confirmation code field when 2FA is enabled", async () => {
    vi.mocked(totpStatus).mockResolvedValue({
      data: { totp_enabled: true },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AccountSettingsPanel />);

    expect(
      await screen.findByLabelText(/confirmation code/i),
    ).toBeInTheDocument();
  });

  it("keeps email change disabled until a 2FA code is entered", async () => {
    render(<AccountSettingsPanel />);
    // Without 2FA, the 2FA field is not shown; password gates the change.
    await screen.findByLabelText(/account password/i);
    expect(screen.queryByLabelText(/^2fa code$/i)).not.toBeInTheDocument();

    const submit = screen.getByRole("button", {
      name: /request email change/i,
    });

    fireEvent.change(screen.getByLabelText(/new email/i), {
      target: { value: "next@auracles.space" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/account password/i), {
      target: { value: "CorrectHorse9" },
    });
    expect(submit).toBeEnabled();
    expect(requestEmailChange).not.toHaveBeenCalled();
  });

  it("submits an email-change request with password and null totp without 2FA", async () => {
    vi.mocked(requestEmailChange).mockResolvedValue({
      data: { message: "Email change verification sent." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AccountSettingsPanel />);
    await screen.findByLabelText(/account password/i);

    fireEvent.change(screen.getByLabelText(/new email/i), {
      target: { value: "next@auracles.space" },
    });
    fireEvent.change(screen.getByLabelText(/account password/i), {
      target: { value: "CorrectHorse9" },
    });
    fireEvent.click(screen.getByRole("button", { name: /request email change/i }));

    await waitFor(() => {
      expect(requestEmailChange).toHaveBeenCalledWith({
        body: {
          new_email: "next@auracles.space",
          password: "CorrectHorse9",
          totp_code: null,
        },
        headers: { Authorization: "Bearer access-token" },
      });
    });
  });

  it("includes the 2FA code in the email-change request when 2FA is enabled", async () => {
    vi.mocked(totpStatus).mockResolvedValue({
      data: { totp_enabled: true },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(requestEmailChange).mockResolvedValue({
      data: { message: "Email change verification sent." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<AccountSettingsPanel />);
    const totpField = await screen.findByLabelText(/^2fa code$/i);

    fireEvent.change(screen.getByLabelText(/new email/i), {
      target: { value: "next@auracles.space" },
    });
    fireEvent.change(screen.getByLabelText(/account password/i), {
      target: { value: "CorrectHorse9" },
    });
    fireEvent.change(totpField, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /request email change/i }));

    await waitFor(() => {
      expect(requestEmailChange).toHaveBeenCalledWith({
        body: {
          new_email: "next@auracles.space",
          password: "CorrectHorse9",
          totp_code: "123456",
        },
        headers: { Authorization: "Bearer access-token" },
      });
    });
  });

  it("submits a delete-account request and shows blocked reasons from the GDPR endpoint", async () => {
    vi.mocked(totpStatus).mockResolvedValue({
      data: { totp_enabled: true },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    const blockedResponse = {
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
    };
    vi.mocked(requestAccountDeletion).mockResolvedValue({
      data: blockedResponse,
      error: blockedResponse,
      response: new Response(null, { status: 409 }),
    });

    render(<AccountSettingsPanel />);
    await screen.findByText(/no data export has been requested yet/i);

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
      await screen.findByText(
        /deletion is blocked until the obligations below are resolved/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/held escrow/i)).toBeInTheDocument();
  });

  it("loads the latest data export status and opens a ready bundle download", async () => {
    vi.mocked(getLatestDataExportStatusV1GdprExportsLatestGet).mockResolvedValue({
      data: {
        completed_at: "2026-06-12T09:30:00Z",
        expires_at: "2026-06-19T09:30:00Z",
        failure_reason: null,
        id: "export-1",
        requested_at: "2026-06-12T09:00:00Z",
        status: "ready",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(
      downloadDataExportV1GdprExportsExportRequestIdDownloadGet,
    ).mockResolvedValue({
      data: undefined,
      error: undefined,
      response: {
        ok: true,
        redirected: true,
        status: 200,
        url: "https://s3.test/gdpr/export-1.json",
      } as Response,
    });

    render(<AccountSettingsPanel />);

    const exportSection = await screen.findByRole("region", {
      name: /data export/i,
    });

    expect(within(exportSection).getByText(/ready for download/i)).toBeInTheDocument();

    fireEvent.click(
      within(exportSection).getByRole("button", { name: /download latest export/i }),
    );

    await waitFor(() => {
      expect(
        downloadDataExportV1GdprExportsExportRequestIdDownloadGet,
      ).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer access-token" },
        path: { export_request_id: "export-1" },
        redirect: "manual",
      });
    });
    expect(location.assign).toHaveBeenCalledWith(
      "http://localhost:8000/v1/gdpr/exports/export-1/download?token=access-token",
    );
  });

  it("requests a new data export and renders the pending state", async () => {
    vi.mocked(requestDataExportV1GdprExportsPost).mockResolvedValue({
      data: {
        completed_at: null,
        expires_at: null,
        failure_reason: null,
        id: "export-2",
        requested_at: "2026-06-12T10:00:00Z",
        status: "pending",
      },
      error: undefined,
      response: new Response(null, { status: 202 }),
    });

    render(<AccountSettingsPanel />);

    const exportSection = await screen.findByRole("region", {
      name: /data export/i,
    });

    fireEvent.click(
      within(exportSection).getByRole("button", { name: /request export/i }),
    );

    await waitFor(() => {
      expect(requestDataExportV1GdprExportsPost).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer access-token" },
      });
    });
    expect(
      await within(exportSection).findByText(/export requested\. we will prepare/i),
    ).toBeInTheDocument();
  });

  it("polls a pending export and reveals the download when it becomes ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // Mount load: no export yet. Then the poll observes the ready bundle.
    vi.mocked(getLatestDataExportStatusV1GdprExportsLatestGet)
      .mockResolvedValueOnce({
        data: undefined,
        error: { detail: "No data export request found." },
        response: new Response(null, { status: 404 }),
      })
      .mockResolvedValue({
        data: {
          id: "export-9",
          status: "ready",
          requested_at: "2026-06-12T10:00:00Z",
          completed_at: "2026-06-12T10:05:00Z",
          expires_at: "2026-06-19T10:05:00Z",
          failure_reason: null,
        },
        error: undefined,
        response: new Response(null, { status: 200 }),
      });
    vi.mocked(requestDataExportV1GdprExportsPost).mockResolvedValue({
      data: {
        id: "export-9",
        status: "pending",
        requested_at: "2026-06-12T10:00:00Z",
        completed_at: null,
        expires_at: null,
        failure_reason: null,
      },
      error: undefined,
      response: new Response(null, { status: 202 }),
    });

    render(<AccountSettingsPanel />);
    const exportSection = await screen.findByRole("region", {
      name: /data export/i,
    });

    fireEvent.click(
      within(exportSection).getByRole("button", { name: /request export/i }),
    );
    await screen.findByText(/export requested\. we will prepare/i);

    // No download yet while pending.
    expect(
      within(exportSection).queryByRole("button", { name: /download/i }),
    ).not.toBeInTheDocument();

    // Advance to the next poll tick; the status flips to ready.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(
      within(exportSection).getByRole("button", { name: /download/i }),
    ).toBeInTheDocument();
    vi.useRealTimers();
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

    // The "delete account" region renders in both the default and scheduled
    // states, so wait for the scheduled copy itself rather than asserting
    // synchronously against the still-pending status fetch.
    expect(
      await within(deletionSection).findByText(
        /your account is scheduled for deletion/i,
      ),
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
