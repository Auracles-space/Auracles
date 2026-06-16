"use client";

/**
 * Resend-verification action shared by the register success panel and the
 * verify-email page.
 *
 * Re-requests a verification email for a given address via the generated
 * client. The backend returns a no-enumeration response, so the button never
 * reveals whether the address exists. Maps to FR-AUTH-003.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { isEmail } from "@/lib/forms/validators";
import { resendVerificationV1AuthResendVerificationPost as resendVerification } from "@/lib/generated/sdk.gen";

import { FormMessage } from "./form-message";

type ResendVerificationButtonProps = {
  email: string;
};

/**
 * Render a button that re-sends the verification email for `email`.
 *
 * @param props - The recipient address; the button is disabled until it is a
 *   syntactically valid email.
 */
export function ResendVerificationButton({
  email,
}: ResendVerificationButtonProps) {
  const [isSending, setIsSending] = useState(false);
  const [status, setStatus] = useState<{
    kind: "error" | "success";
    message: string;
  } | null>(null);

  async function resend(): Promise<void> {
    setStatus(null);
    setIsSending(true);
    configureBrowserClient();

    const result = await resendVerification({ body: { email: email.trim() } });
    setIsSending(false);

    if (!result.response.ok) {
      setStatus({ kind: "error", message: describeGeneratedError(result.error) });
      return;
    }

    setStatus({
      kind: "success",
      message: result.data?.message ?? "Verification email sent.",
    });
  }

  return (
    <div className="space-y-2">
      <Button
        className="w-full"
        disabled={!isEmail(email) || isSending}
        loading={isSending}
        onClick={resend}
        type="button"
        variant="secondary"
      >
        {isSending ? "Sending" : "Resend verification email"}
      </Button>
      {status ? <FormMessage kind={status.kind} message={status.message} /> : null}
    </div>
  );
}
