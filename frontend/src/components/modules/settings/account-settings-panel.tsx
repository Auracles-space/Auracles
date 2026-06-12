"use client";

/**
 * Account identity and exit settings panel.
 *
 * Provides email-change controls plus the single user-facing GDPR delete-account
 * flow. The legacy self-service deactivation action has been retired in favor
 * of the cooling-off deletion workflow.
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  cancelAccountDeletion,
  getAccountDeletionStatus,
  requestAccountDeletion,
  requestEmailChange,
} from "@/lib/generated/sdk.gen";
import type { AccountDeletionStatusResponse } from "@/lib/generated/types.gen";

import { FormField } from "../auth/form-field";
import { FormMessage } from "../auth/form-message";

type PendingDeleteAction = "cancel" | "request" | null;

/**
 * Detect whether a generated-client error contains structured deletion status.
 *
 * @param value - Unknown generated-client error payload.
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
 * Render email-change and GDPR delete-account controls.
 */
export function AccountSettingsPanel() {
  const [deletionError, setDeletionError] = useState<string | null>(null);
  const [deletionPassword, setDeletionPassword] = useState("");
  const [deletionPending, setDeletionPending] = useState<PendingDeleteAction>(null);
  const [deletionStatus, setDeletionStatus] =
    useState<AccountDeletionStatusResponse | null>(null);
  const [deletionTotp, setDeletionTotp] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [emailMessage, setEmailMessage] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [statusLoading, setStatusLoading] = useState(true);
  const [totpCode, setTotpCode] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadDeletionStatus(): Promise<void> {
      configureBrowserClient();
      const result = await getAccountDeletionStatus({
        headers: getAccessTokenHeaders(),
      });

      if (!mounted) {
        return;
      }

      setStatusLoading(false);
      if (!result.response.ok || !result.data) {
        setDeletionError(describeGeneratedError(result.error));
        return;
      }

      setDeletionError(null);
      setDeletionStatus(result.data);
    }

    void loadDeletionStatus();
    return () => {
      mounted = false;
    };
  }, []);

  const scheduledDeletionDate = useMemo(
    () => formatScheduledFor(deletionStatus?.scheduled_for),
    [deletionStatus?.scheduled_for],
  );
  const hasScheduledDeletion = deletionStatus?.status === "scheduled";

  async function submitEmailChange(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setEmailError(null);
    setEmailMessage(null);

    if (totpCode.trim().length < 6) {
      setEmailError("Enter a 2FA code.");
      return;
    }

    configureBrowserClient();
    const result = await requestEmailChange({
      body: { new_email: newEmail.trim(), totp_code: totpCode.trim() },
      headers: getAccessTokenHeaders(),
    });

    if (!result.response.ok) {
      setEmailError(describeGeneratedError(result.error));
      return;
    }

    setEmailMessage(result.data?.message ?? "Email change verification sent.");
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
        password: deletionPassword,
        totp_code: deletionTotp.trim() || null,
      },
      headers: getAccessTokenHeaders(),
    });
    setDeletionPending(null);

    if (!result.response.ok) {
      if (isAccountDeletionStatusResponse(result.error)) {
        setDeletionStatus(result.error);
        setDeletionPassword("");
        setDeletionTotp("");
        return;
      }

      setDeletionError(describeGeneratedError(result.error));
      return;
    }

    setDeletionStatus(result.data ?? null);
    setDeletionPassword("");
    setDeletionTotp("");
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
        className="space-y-5 border-b border-border-strong pb-8"
        onSubmit={submitEmailChange}
      >
        <div>
          <h2 className="font-heading text-xl font-semibold text-foreground">
            Email address
          </h2>
          <p className="mt-2 text-sm leading-6 text-foreground-muted">
            Confirm with 2FA, then verify the new address from your email.
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
        <FormField
          autoComplete="one-time-code"
          label="2FA code"
          name="totp_code"
          onChange={(event) => setTotpCode(event.target.value)}
          value={totpCode}
        />
        <Button type="submit">Request email change</Button>
      </form>

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
          <p className="rounded-control border border-border-default bg-surface-2 px-3 py-2 text-sm text-foreground-muted">
            Loading deletion status...
          </p>
        ) : null}

        {deletionError ? (
          <FormMessage kind="error" message={deletionError} />
        ) : null}

        {deletionStatus?.status === "scheduled" ? (
          <div className="space-y-4 rounded-control border border-success/30 bg-success/10 p-4">
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
              <div className="space-y-3 rounded-control border border-error/30 bg-error/10 p-4">
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

            <FormField
              autoComplete="current-password"
              label="Current password"
              name="password"
              onChange={(event) => setDeletionPassword(event.target.value)}
              required
              type="password"
              value={deletionPassword}
            />
            <FormField
              autoComplete="one-time-code"
              helper="Required when 2FA is enabled on your account."
              label="Confirmation code"
              name="deletion_totp_code"
              onChange={(event) => setDeletionTotp(event.target.value)}
              value={deletionTotp}
            />
            <Button
              disabled={deletionPending === "request" || hasScheduledDeletion}
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
