"use client";

/**
 * Account identity settings panel.
 *
 * Provides email-change and deactivation workflows through generated client
 * calls. Backend endpoints enforce password checks, TOTP checks, session
 * revocation, and audit writes.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { deactivateAccount, requestEmailChange } from "@/lib/generated/sdk.gen";

import { FormField } from "../auth/form-field";
import { FormMessage } from "../auth/form-message";

/**
 * Render email-change and account-deactivation controls.
 */
export function AccountSettingsPanel() {
  const [deactivateMessage, setDeactivateMessage] = useState<string | null>(null);
  const [deactivatePassword, setDeactivatePassword] = useState("");
  const [deactivateTotp, setDeactivateTotp] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [emailMessage, setEmailMessage] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [totpCode, setTotpCode] = useState("");

  async function submitEmailChange(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
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

  async function submitDeactivate(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setDeactivateMessage(null);

    configureBrowserClient();
    const result = await deactivateAccount({
      body: {
        password: deactivatePassword,
        totp_code: deactivateTotp.trim() || null,
      },
      headers: getAccessTokenHeaders(),
    });

    if (!result.response.ok) {
      setDeactivateMessage(describeGeneratedError(result.error));
      return;
    }

    setDeactivateMessage(result.data?.message ?? "Account deactivated.");
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

      <form className="space-y-5" onSubmit={submitDeactivate}>
        <div>
          <h2 className="font-heading text-xl font-semibold text-foreground">
            Deactivate account
          </h2>
          <p className="mt-2 text-sm leading-6 text-foreground-muted">
            Deactivation revokes active sessions. Published marketplace records
            remain governed by their existing visibility rules.
          </p>
        </div>
        {deactivateMessage ? (
          <FormMessage
            kind={deactivateMessage.includes("deactivated") ? "success" : "error"}
            message={deactivateMessage}
          />
        ) : null}
        <FormField
          autoComplete="current-password"
          label="Current password"
          name="password"
          onChange={(event) => setDeactivatePassword(event.target.value)}
          required
          type="password"
          value={deactivatePassword}
        />
        <FormField
          autoComplete="one-time-code"
          label="Confirmation code"
          name="deactivate_totp_code"
          onChange={(event) => setDeactivateTotp(event.target.value)}
          value={deactivateTotp}
        />
        <Button type="submit" variant="destructive">
          Deactivate account
        </Button>
      </form>
    </div>
  );
}
