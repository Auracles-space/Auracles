"use client";

/**
 * TOTP setup panel for authenticated users.
 *
 * Starts TOTP enrollment, displays the QR payload returned by the backend, and
 * verifies the first code. Sensitive operations still require backend JWT
 * verification and account state checks.
 */
import { useState } from "react";
import Image from "next/image";

import { Button } from "@/components/ui/button";
import { isLengthBetween } from "@/lib/forms/validators";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { setupTotp, verifyTotp } from "@/lib/generated/sdk.gen";

import { FormMessage } from "./form-message";
import { TotpInput } from "./totp-input";

type SetupState = {
  backupCodes: string[];
  provisioningUri: string;
  qrPngBase64: string;
};

/**
 * Render the authenticated TOTP setup workflow.
 */
export function TotpSetupPanel() {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [setup, setSetup] = useState<SetupState | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const canVerify = isLengthBetween(code, 6, 6);

  async function copyBackupCodes(codes: string[]): Promise<void> {
    await navigator.clipboard.writeText(codes.join("\n"));
    setCopied(true);
  }

  async function startSetup(): Promise<void> {
    setError(null);
    setSuccess(null);
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

    setSuccess("Two-factor authentication is enabled.");
    setCode("");
    setSetup(null);
    setCopied(false);
  }

  return (
    <form className="space-y-5" onSubmit={verifySetup}>
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Enable 2FA
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Add an authenticator app before changing sensitive account settings.
        </p>
      </div>
      {error ? <FormMessage kind="error" message={error} /> : null}
      {success ? <FormMessage kind="success" message={success} /> : null}

      {setup ? (
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
          <div className="rounded-[20px] border border-border-strong bg-surface-2 p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-heading text-sm font-semibold text-foreground">
                Backup codes
              </h3>
              <button
                className="inline-flex min-h-9 items-center justify-center rounded-lg border border-border-default bg-background px-3 py-1.5 text-xs font-medium text-foreground transition hover:bg-surface-1"
                onClick={() => void copyBackupCodes(setup.backupCodes)}
                type="button"
              >
                {copied ? "Copied" : "Copy codes"}
              </button>
            </div>
            <ul className="mt-3 grid gap-2 text-sm text-foreground-muted sm:grid-cols-2">
              {setup.backupCodes.map((backupCode) => (
                <li className="font-mono" key={backupCode}>
                  {backupCode}
                </li>
              ))}
            </ul>
          </div>
          <Button className="w-full" disabled={isLoading || !canVerify} type="submit">
            {isLoading ? "Verifying" : "Verify and enable"}
          </Button>
        </div>
      ) : success ? null : (
        <Button className="w-full" disabled={isLoading} onClick={startSetup}>
          {isLoading ? "Preparing setup" : "Start 2FA setup"}
        </Button>
      )}
    </form>
  );
}
