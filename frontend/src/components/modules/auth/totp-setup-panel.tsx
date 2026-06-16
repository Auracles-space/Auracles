"use client";

/**
 * TOTP management panel for authenticated users.
 *
 * Handles the full authenticator lifecycle: first-time enrollment, moving 2FA
 * to a new device (disable + re-enroll), and regenerating backup codes. Every
 * destructive step still requires backend JWT verification plus proof of a
 * current TOTP or backup code.
 */
import { useEffect, useState } from "react";
import Image from "next/image";

import { Button } from "@/components/ui/button";
import { isLengthBetween } from "@/lib/forms/validators";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  disableTotp,
  regenerateBackupCodes,
  setupTotp,
  totpStatus,
  verifyTotp,
} from "@/lib/generated/sdk.gen";

import { BackupCodesCard } from "./backup-codes-card";
import { FormMessage } from "./form-message";
import { TotpInput } from "./totp-input";

type SetupState = {
  backupCodes: string[];
  provisioningUri: string;
  qrPngBase64: string;
};

type AccountStatus = {
  enabled: boolean;
  backupCodesRemaining: number;
};

/** Which confirm-code prompt is currently open on the enabled panel. */
type PendingAction = "reset" | "regenerate" | null;

/**
 * Render the authenticated TOTP management workflow.
 */
export function TotpSetupPanel() {
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [code, setCode] = useState("");
  const [confirmCode, setConfirmCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [setup, setSetup] = useState<SetupState | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction>(null);
  const [newBackupCodes, setNewBackupCodes] = useState<string[] | null>(null);

  const canVerify = isLengthBetween(code, 6, 6);
  const canConfirm = confirmCode.trim().length >= 6;

  useEffect(() => {
    void refreshStatus();
  }, []);

  async function refreshStatus(): Promise<void> {
    configureBrowserClient();
    const result = await totpStatus({ headers: getAccessTokenHeaders() });
    if (result.response.ok && result.data) {
      setStatus({
        enabled: result.data.totp_enabled,
        backupCodesRemaining: result.data.backup_codes_remaining,
      });
    } else {
      setStatus({ enabled: false, backupCodesRemaining: 0 });
    }
  }

  function resetTransientState(): void {
    setError(null);
    setSuccess(null);
    setPending(null);
    setNewBackupCodes(null);
    setConfirmCode("");
  }

  async function startSetup(): Promise<void> {
    resetTransientState();
    setIsLoading(true);
    configureBrowserClient();
    const result = await setupTotp({ headers: getAccessTokenHeaders() });
    setIsLoading(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSetup({
      backupCodes: result.data.backup_codes,
      provisioningUri: result.data.provisioning_uri,
      qrPngBase64: result.data.qr_png_base64,
    });
  }

  async function verifySetup(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setError(null);

    if (code.length !== 6) {
      setError("Enter a valid 2FA code.");
      return;
    }

    setIsLoading(true);
    configureBrowserClient();
    const result = await verifyTotp({
      body: { code },
      headers: getAccessTokenHeaders(),
    });
    setIsLoading(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSuccess("Setup complete — your authenticator is ready.");
    setCode("");
    setSetup(null);
    setStatus({ enabled: true, backupCodesRemaining: 10 });
  }

  async function confirmReset(): Promise<void> {
    setError(null);
    setIsLoading(true);
    configureBrowserClient();
    const result = await disableTotp({
      body: { code: confirmCode.trim() },
      headers: getAccessTokenHeaders(),
    });

    if (!result.response.ok) {
      setIsLoading(false);
      setError(describeGeneratedError(result.error));
      return;
    }

    // Disable succeeded — immediately start a fresh enrollment for the new
    // device. startSetup clears the pending prompt and flips to the QR view.
    await startSetup();
  }

  async function confirmRegenerate(): Promise<void> {
    setError(null);
    setIsLoading(true);
    configureBrowserClient();
    const result = await regenerateBackupCodes({
      body: { code: confirmCode.trim() },
      headers: getAccessTokenHeaders(),
    });
    setIsLoading(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setPending(null);
    setConfirmCode("");
    setNewBackupCodes(result.data.backup_codes);
    setStatus({ enabled: true, backupCodesRemaining: 10 });
  }

  function dismissNewBackupCodes(): void {
    setNewBackupCodes(null);
  }

  const heading = (
    <div>
      <h2 className="font-heading text-xl font-semibold text-foreground">
        {status?.enabled ? "Two-factor authentication" : "Enable 2FA"}
      </h2>
      <p className="mt-2 text-sm leading-6 text-foreground-muted">
        Add an authenticator app before changing sensitive account settings.
      </p>
    </div>
  );

  if (status === null) {
    return (
      <div className="space-y-5">
        {heading}
        <p className="text-sm text-foreground-muted" data-testid="loading">
          Checking two-factor status…
        </p>
      </div>
    );
  }

  // Active enrollment (first-time setup or re-enrollment after a reset).
  if (setup) {
    return (
      <form className="space-y-5" onSubmit={verifySetup}>
        {heading}
        {error ? <FormMessage kind="error" message={error} /> : null}
        <div className="space-y-4">
          <div className="rounded-[20px] border border-border-strong bg-surface-2 p-4 shadow-sm">
            <Image
              alt="Authenticator QR code"
              className="mx-auto h-48 w-48"
              height={192}
              unoptimized
              src={`data:image/png;base64,${setup.qrPngBase64}`}
              width={192}
            />
            <p className="mt-3 break-all text-xs leading-5 text-foreground-muted">
              {setup.provisioningUri}
            </p>
          </div>
          <TotpInput onChange={setCode} value={code} />
          <BackupCodesCard codes={setup.backupCodes} />
          <Button className="w-full" disabled={isLoading || !canVerify} type="submit">
            {isLoading ? "Verifying" : "Verify and enable"}
          </Button>
        </div>
      </form>
    );
  }

  // Freshly regenerated backup codes (shown once).
  if (newBackupCodes) {
    return (
      <div className="space-y-5">
        {heading}
        <FormMessage kind="success" message="New backup codes generated." />
        <BackupCodesCard codes={newBackupCodes} />
        <Button className="w-full" onClick={dismissNewBackupCodes} variant="secondary">
          Done
        </Button>
      </div>
    );
  }

  // Enabled account: status, re-enroll, and regenerate controls.
  if (status.enabled) {
    return (
      <div className="space-y-5">
        {heading}
        {error ? <FormMessage kind="error" message={error} /> : null}
        {success ? <FormMessage kind="success" message={success} /> : null}

        <div className="rounded-[20px] border border-border-strong bg-surface-2 p-4 shadow-sm">
          <p className="text-sm font-medium text-foreground">
            Two-factor authentication is enabled.
          </p>
          <p className="mt-1 text-sm text-foreground-muted">
            {status.backupCodesRemaining} backup{" "}
            {status.backupCodesRemaining === 1 ? "code" : "codes"} remaining.
          </p>
        </div>

        {pending ? (
          <div className="space-y-3 rounded-[20px] border border-border-strong bg-surface-2 p-4 shadow-sm">
            <label className="block" htmlFor="confirm-code">
              <span className="text-sm font-medium text-foreground">
                Authenticator or backup code
              </span>
              <input
                autoComplete="one-time-code"
                className="mt-2 min-h-12 w-full rounded-control border border-border-strong bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-subtle focus:border-accent focus:ring-1 focus:ring-accent"
                id="confirm-code"
                onChange={(event) => setConfirmCode(event.target.value.trim())}
                placeholder="Enter a current code"
                type="text"
                value={confirmCode}
              />
            </label>
            <p className="text-xs leading-5 text-foreground-muted">
              {pending === "reset"
                ? "Confirm to disable 2FA on the old device and scan a fresh QR code."
                : "Confirm to replace your remaining backup codes with a new set."}
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                className="w-full"
                disabled={isLoading || !canConfirm}
                onClick={() =>
                  void (pending === "reset"
                    ? confirmReset()
                    : confirmRegenerate())
                }
              >
                {isLoading
                  ? "Working"
                  : pending === "reset"
                    ? "Confirm and re-enroll"
                    : "Confirm and regenerate"}
              </Button>
              <Button
                className="w-full"
                disabled={isLoading}
                onClick={() => {
                  setPending(null);
                  setConfirmCode("");
                  setError(null);
                }}
                variant="secondary"
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <Button
              className="w-full"
              onClick={() => {
                resetTransientState();
                setPending("reset");
              }}
              variant="secondary"
            >
              Set up on a new device
            </Button>
            <Button
              className="w-full"
              onClick={() => {
                resetTransientState();
                setPending("regenerate");
              }}
              variant="secondary"
            >
              Regenerate backup codes
            </Button>
          </div>
        )}
      </div>
    );
  }

  // Not enabled: first-time setup entry point.
  return (
    <div className="space-y-5">
      {heading}
      {error ? <FormMessage kind="error" message={error} /> : null}
      <Button className="w-full" disabled={isLoading} onClick={startSetup}>
        {isLoading ? "Preparing setup" : "Start 2FA setup"}
      </Button>
    </div>
  );
}
