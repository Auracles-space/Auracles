"use client";

/**
 * TOTP challenge completion form.
 *
 * Used after `/login` returns a challenge token instead of a browser session.
 * A valid code or backup code trades the challenge for access token JSON and
 * refresh/session cookies set by the backend.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { allValid, isNonEmpty } from "@/lib/forms/validators";
import {
  authTokenStore,
  setAccessTokenFromJwt,
} from "@/lib/auth/token-store";
import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { getRoleLandingPath } from "@/lib/auth/route-guards";
import { safeInternalPath } from "@/lib/url/safe-href";
import { verifyTotpLogin } from "@/lib/generated/sdk.gen";

import { BackupCodeInput } from "./backup-code-input";
import { FormMessage } from "./form-message";
import { TotpInput } from "./totp-input";

type TotpChallengeFormProps = {
  challengeToken: string;
  next?: string;
  onAuthenticated?: (location: string) => void;
};

/**
 * Render the login 2FA challenge form.
 *
 * @param props - Challenge token, resume-intent path, and optional router.
 */
export function TotpChallengeForm({
  challengeToken,
  next,
  onAuthenticated,
}: TotpChallengeFormProps) {
  const safeNext = safeInternalPath(next);
  const [backupCode, setBackupCode] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [useBackup, setUseBackup] = useState(false);
  const activeCredential = useBackup ? backupCode : code;
  const canSubmit = allValid(
    isNonEmpty(challengeToken),
    activeCredential.trim().length >= 6,
  );

  function navigateTo(location: string): void {
    if (onAuthenticated) {
      onAuthenticated(location);
      return;
    }
    window.location.assign(location);
  }

  async function submitChallenge(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    const credential = useBackup ? backupCode : code;
    setError(null);

    if (!challengeToken) {
      setError("Login challenge token is missing.");
      return;
    }
    if (credential.length < 6) {
      setError("Enter a valid 2FA code.");
      return;
    }

    setIsSubmitting(true);
    configureBrowserClient();
    const result = await verifyTotpLogin({
      body: { challenge_token: challengeToken, code: credential },
    });
    setIsSubmitting(false);

    if (!result.response.ok || !result.data?.access_token) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setAccessTokenFromJwt(result.data.access_token);
    navigateTo(safeNext ?? getRoleLandingPath(authTokenStore.getState().roles));
  }

  return (
    <form className="space-y-5" onSubmit={submitChallenge}>
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Two-factor challenge
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Confirm this login with your authenticator app or a recovery code.
        </p>
      </div>
      {error ? <FormMessage kind="error" message={error} /> : null}
      {useBackup ? (
        <BackupCodeInput onChange={setBackupCode} value={backupCode} />
      ) : (
        <TotpInput onChange={setCode} value={code} />
      )}
      <label className="flex min-h-12 items-center gap-3 text-sm text-foreground-muted">
        <input
          checked={useBackup}
          className="h-4 w-4 accent-accent"
          onChange={(event) => setUseBackup(event.target.checked)}
          type="checkbox"
        />
        Use a backup code
      </label>
      <Button className="w-full" disabled={!canSubmit} loading={isSubmitting} type="submit">
        Verify login
      </Button>
    </form>
  );
}
