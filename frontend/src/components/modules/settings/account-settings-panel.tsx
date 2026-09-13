"use client";

/**
 * Account identity and exit settings panel.
 *
 * Provides email-change controls, GDPR export access, and the single
 * user-facing GDPR delete-account flow. The legacy self-service deactivation
 * action has been retired in favor of the cooling-off deletion workflow.
 * Email change and deletion are sensitive actions: the API requires a step-up
 * 2FA window, which the global step-up prompt handles when a call is refused.
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { allValid, isEmail, isNonEmpty } from "@/lib/forms/validators";
import {
  cancelAccountDeletion,
  downloadDataExportV1GdprExportsExportRequestIdDownloadGet,
  getAccountDeletionStatus,
  getCurrentUser,
  getLatestDataExportStatusV1GdprExportsLatestGet,
  requestAccountDeletion,
  requestDataExportV1GdprExportsPost,
  requestEmailChange,
} from "@/lib/generated/sdk.gen";
import type {
  AccountDeletionStatusResponse,
  DataExportRequestResponse,
} from "@/lib/generated/types.gen";

import { FormField } from "../auth/form-field";
import { FormMessage } from "../auth/form-message";

type PendingDeleteAction = "cancel" | "request" | null;
type PendingExportAction = "download" | "request" | null;

/**
 * Detect whether an unknown value is a structured deletion-status payload.
 *
 * @param value - Unknown payload candidate.
 */
function isAccountDeletionStatusResponse(
  value: unknown,
): value is AccountDeletionStatusResponse {
  return Boolean(
    value &&
      typeof value === "object" &&
      "blocked_reasons" in value &&
      "status" in value,
  );
}

/**
 * Extract structured deletion status from generated-client error payloads.
 *
 * Supports both direct response bodies and `{ detail: {...} }` wrappers used
 * by some generated error shapes.
 *
 * @param value - Unknown generated-client error payload.
 * @returns Parsed deletion status when present.
 */
function getAccountDeletionStatusError(
  value: unknown,
): AccountDeletionStatusResponse | null {
  if (isAccountDeletionStatusResponse(value)) {
    return value;
  }
  if (
    value &&
    typeof value === "object" &&
    "detail" in value &&
    isAccountDeletionStatusResponse(value.detail)
  ) {
    return value.detail;
  }
  return null;
}

/**
 * Format a scheduled deletion timestamp for concise account-settings copy.
 *
 * @param value - ISO timestamp from the API.
 */
function formatScheduledFor(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Format a GDPR export timestamp for compact settings copy.
 *
 * @param value - ISO timestamp from the API.
 */
function formatTimestamp(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Render email-change, GDPR export, and delete-account controls.
 */
export function AccountSettingsPanel() {
  const [deletionError, setDeletionError] = useState<string | null>(null);
  const [deletionPassword, setDeletionPassword] = useState("");
  const [deletionPending, setDeletionPending] = useState<PendingDeleteAction>(null);
  const [deletionStatus, setDeletionStatus] =
    useState<AccountDeletionStatusResponse | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [emailMessage, setEmailMessage] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [exportPending, setExportPending] = useState<PendingExportAction>(null);
  const [exportStatus, setExportStatus] = useState<DataExportRequestResponse | null>(
    null,
  );
  const [exportStatusLoading, setExportStatusLoading] = useState(true);
  const [newEmail, setNewEmail] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [statusLoading, setStatusLoading] = useState(true);
  // Passwordless (e.g. Google) accounts re-auth without a password: the
  // verification link / 2FA stands in, and they can set a password to recover.
  const [hasPassword, setHasPassword] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function loadSettingsState(): Promise<void> {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      const [deletionResult, exportResult, userResult] = await Promise.all([
        getAccountDeletionStatus({
          headers,
        }),
        getLatestDataExportStatusV1GdprExportsLatestGet({
          headers,
        }),
        getCurrentUser({ headers }),
      ]);

      if (!mounted) {
        return;
      }

      if (userResult.response.ok && userResult.data) {
        setHasPassword(userResult.data.has_password ?? true);
      }

      setStatusLoading(false);
      if (!deletionResult.response.ok || !deletionResult.data) {
        setDeletionError(describeGeneratedError(deletionResult.error));
      } else {
        setDeletionError(null);
        setDeletionStatus(deletionResult.data);
      }

      setExportStatusLoading(false);
      if (exportResult.response.status === 404) {
        setExportError(null);
        setExportStatus(null);
        return;
      }
      if (!exportResult.response.ok || !exportResult.data) {
        setExportError(describeGeneratedError(exportResult.error));
        return;
      }

      setExportError(null);
      setExportStatus(exportResult.data);
    }

    void loadSettingsState();
    return () => {
      mounted = false;
    };
  }, []);

  // Export generation is async (Celery). While a request is pending/processing,
  // poll the latest status so the download surfaces without a manual reload.
  const exportStatusValue = exportStatus?.status;
  useEffect(() => {
    if (exportStatusValue !== "pending" && exportStatusValue !== "processing") {
      return;
    }
    let active = true;
    const interval = setInterval(async () => {
      configureBrowserClient();
      const latest = await getLatestDataExportStatusV1GdprExportsLatestGet({
        headers: getAccessTokenHeaders(),
      });
      if (!active) {
        return;
      }
      if (latest.response.ok && latest.data) {
        setExportStatus(latest.data);
      }
    }, 3000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [exportStatusValue]);

  const scheduledDeletionDate = useMemo(
    () => formatScheduledFor(deletionStatus?.scheduled_for),
    [deletionStatus?.scheduled_for],
  );
  const exportReadyAt = useMemo(
    () => formatTimestamp(exportStatus?.completed_at),
    [exportStatus?.completed_at],
  );
  const exportExpiryDate = useMemo(
    () => formatTimestamp(exportStatus?.expires_at),
    [exportStatus?.expires_at],
  );
  const hasScheduledDeletion = deletionStatus?.status === "scheduled";
  const isExportActive =
    exportStatus?.status === "pending" || exportStatus?.status === "processing";
  const canSubmitEmailChange = allValid(
    isEmail(newEmail),
    !hasPassword || isNonEmpty(emailPassword),
  );
  const canSubmitDeletion = !hasPassword || isNonEmpty(deletionPassword);

  async function submitEmailChange(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setEmailError(null);
    setEmailMessage(null);

    // Passwordless accounts have no password to confirm; the verification link
    // sent to the new address is the proof of intent.
    if (hasPassword && !isNonEmpty(emailPassword)) {
      setEmailError("Enter your current password.");
      return;
    }

    configureBrowserClient();
    const result = await requestEmailChange({
      body: {
        new_email: newEmail.trim(),
        password: hasPassword ? emailPassword : undefined,
      },
      headers: getAccessTokenHeaders(),
    });

    if (!result.response.ok) {
      setEmailError(describeGeneratedError(result.error));
      return;
    }

    setEmailMessage(result.data?.message ?? "Email change verification sent.");
    setEmailPassword("");
  }

  async function submitExportRequest(): Promise<void> {
    setExportError(null);
    setExportMessage(null);
    setExportPending("request");

    configureBrowserClient();
    const result = await requestDataExportV1GdprExportsPost({
      headers: getAccessTokenHeaders(),
    });
    setExportPending(null);

    if (!result.response.ok || !result.data) {
      setExportError(describeGeneratedError(result.error));
      return;
    }

    setExportStatus(result.data);
    setExportMessage("Export requested. We will prepare your JSON bundle shortly.");
  }

  async function submitExportDownload(): Promise<void> {
    if (!exportStatus?.id) {
      return;
    }

    setExportError(null);
    setExportMessage(null);
    setExportPending("download");

    configureBrowserClient();
    try {
      const result = await downloadDataExportV1GdprExportsExportRequestIdDownloadGet({
        headers: getAccessTokenHeaders(),
        path: { export_request_id: exportStatus.id },
      });
      setExportPending(null);

      if (!result.response.ok) {
        setExportError(describeGeneratedError(result.error));
        return;
      }

      // The endpoint hands back a short-lived presigned S3 URL; navigating to
      // it directly keeps the access token in the Authorization header above.
      if (result.data?.download_url) {
        window.location.assign(result.data.download_url);
        return;
      }

      setExportMessage("Download started.");
    } catch {
      setExportPending(null);
      setExportError("An unexpected error occurred while fetching the export.");
    }
  }

  async function submitDeletionRequest(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setDeletionError(null);
    setDeletionPending("request");

    configureBrowserClient();
    const result = await requestAccountDeletion({
      body: {
        password: hasPassword ? deletionPassword : undefined,
      },
      headers: getAccessTokenHeaders(),
    });
    setDeletionPending(null);

    if (!result.response.ok) {
      const deletionStatusError =
        getAccountDeletionStatusError(result.data) ??
        getAccountDeletionStatusError(result.error);
      if (deletionStatusError) {
        setDeletionStatus(deletionStatusError);
        setDeletionPassword("");
        return;
      }

      setDeletionError(describeGeneratedError(result.error));
      return;
    }

    setDeletionStatus(result.data ?? null);
    setDeletionPassword("");
  }

  async function submitDeletionCancel(): Promise<void> {
    setDeletionError(null);
    setDeletionPending("cancel");

    configureBrowserClient();
    const result = await cancelAccountDeletion({
      headers: getAccessTokenHeaders(),
    });
    setDeletionPending(null);

    if (!result.response.ok || !result.data) {
      setDeletionError(describeGeneratedError(result.error));
      return;
    }

    setDeletionStatus(result.data);
  }

  return (
    <div className="space-y-8">
      <form
        className="space-y-5 border-b border-border-default pb-8"
        onSubmit={submitEmailChange}
      >
        <div>
          <h2 className="font-heading text-xl font-semibold text-foreground">
            Email address
          </h2>
          <p className="mt-2 text-sm leading-6 text-foreground-muted">
            {hasPassword
              ? "Confirm with your password, then verify the new address from your email. We notify your current address for security."
              : "Verify the new address from your email. We notify your current address for security."}
          </p>
        </div>
        {emailError ? <FormMessage kind="error" message={emailError} /> : null}
        {emailMessage ? (
          <FormMessage kind="success" message={emailMessage} />
        ) : null}
        <FormField
          autoComplete="email"
          label="New email"
          name="new_email"
          onChange={(event) => setNewEmail(event.target.value)}
          required
          type="email"
          value={newEmail}
        />
        {hasPassword ? (
          <FormField
            autoComplete="current-password"
            label="Account password"
            name="email_change_password"
            onChange={(event) => setEmailPassword(event.target.value)}
            required
            type="password"
            value={emailPassword}
          />
        ) : (
          <p className="text-sm leading-6 text-foreground-muted">
            You signed in with Google, so there&apos;s no password to enter.{" "}
            <a className="font-medium text-accent hover:underline" href="/forgot-password">
              Set a password
            </a>{" "}
            to add email sign-in.
          </p>
        )}
        <Button disabled={!canSubmitEmailChange} type="submit">
          Request email change
        </Button>
      </form>

      <section
        aria-labelledby="data-export-heading"
        className="space-y-5 border-b border-border-default pb-8"
        role="region"
      >
        <div>
          <h2
            className="font-heading text-xl font-semibold text-foreground"
            id="data-export-heading"
          >
            Data export
          </h2>
          <p className="mt-2 text-sm leading-6 text-foreground-muted">
            Request a private JSON export of the personal data linked to your
            account across Auracles.
          </p>
        </div>

        {exportStatusLoading ? (
          <p className="rounded-xl border border-border-default bg-surface-2 px-3 py-2 text-sm text-foreground-muted">
            Loading export status...
          </p>
        ) : null}

        {exportError ? <FormMessage kind="error" message={exportError} /> : null}
        {exportMessage ? (
          <FormMessage kind="success" message={exportMessage} />
        ) : null}

        {exportStatus?.status === "ready" ? (
          <div className="space-y-4 rounded-xl border border-success/30 bg-success/10 p-4">
            <p className="text-sm font-medium text-success">Ready for download.</p>
            <div className="space-y-1 text-sm leading-6 text-foreground-muted">
              {exportReadyAt ? <p>Prepared {exportReadyAt}.</p> : null}
              {exportExpiryDate ? <p>Available until {exportExpiryDate}.</p> : null}
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Button
                disabled={exportPending === "download"}
                onClick={() => void submitExportDownload()}
                type="button"
              >
                {exportPending === "download"
                  ? "Opening..."
                  : "Download latest export"}
              </Button>
              <Button
                disabled={exportPending === "request"}
                onClick={() => void submitExportRequest()}
                type="button"
                variant="secondary"
              >
                {exportPending === "request" ? "Requesting..." : "Request new export"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4 rounded-xl border border-border-default bg-surface-2 p-4">
            <div className="space-y-1 text-sm leading-6 text-foreground-muted">
              {exportStatus?.status === "pending" || exportStatus?.status === "processing" ? (
                <p>Your latest export is being prepared.</p>
              ) : null}
              {exportStatus?.status === "failed" && exportStatus.failure_reason ? (
                <p>{exportStatus.failure_reason}</p>
              ) : null}
              {exportStatus?.status === "expired" ? (
                <p>Your last export expired. Request a fresh bundle to download it.</p>
              ) : null}
              {!exportStatus ? (
                <p>No data export has been requested yet.</p>
              ) : null}
            </div>
            <Button
              disabled={exportPending === "request" || isExportActive}
              onClick={() => void submitExportRequest()}
              type="button"
              variant="secondary"
            >
              {exportPending === "request" ? "Requesting..." : "Request export"}
            </Button>
          </div>
        )}
      </section>

      <section
        aria-labelledby="delete-account-heading"
        className="space-y-5"
        role="region"
      >
        <div>
          <h2
            className="font-heading text-xl font-semibold text-foreground"
            id="delete-account-heading"
          >
            Delete account
          </h2>
          <p className="mt-2 text-sm leading-6 text-foreground-muted">
            Deletion starts a cooling-off window. Active escrow, payouts,
            disputes, projects, or attestations must be resolved before the
            request can proceed.
          </p>
        </div>

        {statusLoading ? (
          <p className="rounded-xl border border-border-default bg-surface-2 px-3 py-2 text-sm text-foreground-muted">
            Loading deletion status...
          </p>
        ) : null}

        {deletionError ? (
          <FormMessage kind="error" message={deletionError} />
        ) : null}

        {deletionStatus?.status === "scheduled" ? (
          <div className="space-y-4 rounded-xl border border-success/30 bg-success/10 p-4">
            <p className="text-sm font-medium text-success">
              Your account is scheduled for deletion.
            </p>
            <p className="text-sm leading-6 text-foreground-muted">
              {scheduledDeletionDate
                ? `You can cancel this request until ${scheduledDeletionDate}.`
                : "You can cancel this request until the cooling-off window ends."}
            </p>
            <Button
              disabled={deletionPending === "cancel"}
              onClick={() => void submitDeletionCancel()}
              type="button"
              variant="secondary"
            >
              {deletionPending === "cancel"
                ? "Cancelling..."
                : "Cancel deletion request"}
            </Button>
          </div>
        ) : (
          <form className="space-y-5" onSubmit={submitDeletionRequest}>
            {deletionStatus?.status === "blocked" ? (
              <div className="space-y-3 rounded-xl border border-error/30 bg-error/10 p-4">
                <p className="text-sm font-medium text-error">
                  Deletion is blocked until the obligations below are resolved.
                </p>
                <ul className="space-y-2 text-sm leading-6 text-foreground">
                  {deletionStatus.blocked_reasons.map((reason) => (
                    <li key={reason.code}>
                      {reason.message}
                      {reason.count ? ` (${reason.count})` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {deletionStatus?.status === "cancelled" ? (
              <FormMessage
                kind="success"
                message="Deletion request cancelled. Your account remains active."
              />
            ) : null}

            {deletionStatus?.status === "completed" ? (
              <FormMessage
                kind="success"
                message="Account deletion has completed."
              />
            ) : null}

            {hasPassword ? (
              <FormField
                autoComplete="current-password"
                label="Current password"
                name="password"
                onChange={(event) => setDeletionPassword(event.target.value)}
                required
                type="password"
                value={deletionPassword}
              />
            ) : (
              <p className="text-sm leading-6 text-foreground-muted">
                You signed in with Google. Deletion starts a cooling-off period
                before anything is removed.
              </p>
            )}
            <Button
              disabled={
                deletionPending === "request" ||
                hasScheduledDeletion ||
                !canSubmitDeletion
              }
              type="submit"
              variant="destructive"
            >
              {deletionPending === "request" ? "Submitting..." : "Delete account"}
            </Button>
          </form>
        )}
      </section>
    </div>
  );
}
