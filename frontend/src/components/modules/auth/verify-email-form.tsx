"use client";

/**
 * Email verification form.
 *
 * Accepts a token from the URL or manual entry, then calls the generated
 * verification endpoint. The backend remains responsible for token validity.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { isNonEmpty } from "@/lib/forms/validators";
import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { verifyEmail } from "@/lib/generated/sdk.gen";

import { FormField } from "./form-field";
import { FormMessage } from "./form-message";
import { ResendVerificationButton } from "./resend-verification-button";

type VerifyEmailFormProps = {
  initialToken?: string;
  initialEmail?: string;
};

/**
 * Render the email verification token submission form.
 *
 * The primary path is the magic link in the verification email (which prefills
 * the token via search params). The manual token field and the resend control
 * are fallbacks for when the link is lost or expired.
 *
 * @param props - Optional token and email captured from search params.
 */
export function VerifyEmailForm({
  initialToken = "",
  initialEmail = "",
}: VerifyEmailFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [token, setToken] = useState(initialToken);
  const [email, setEmail] = useState(initialEmail);
  const canSubmit = isNonEmpty(token);

  async function submitVerification(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsSubmitting(true);
    configureBrowserClient();

    const result = await verifyEmail({ body: { token: token.trim() } });
    setIsSubmitting(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSuccess(result.data?.message ?? "Email verified.");
  }

  return (
    <form className="space-y-5" onSubmit={submitVerification}>
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Verify email
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Confirm your email before accessing protected workspaces.
        </p>
      </div>
      {error ? <FormMessage kind="error" message={error} /> : null}
      {success ? <FormMessage kind="success" message={success} /> : null}
      <FormField
        label="Verification token"
        name="token"
        onChange={(event) => setToken(event.target.value)}
        required
        value={token}
      />
      <Button className="w-full" disabled={isSubmitting || !canSubmit} type="submit">
        {isSubmitting ? "Verifying" : "Verify email"}
      </Button>

      <div className="space-y-3 border-t border-border-default pt-5">
        <p className="text-sm leading-6 text-foreground-muted">
          Didn&apos;t get the email? Enter your address and we&apos;ll send a new
          verification link.
        </p>
        <FormField
          autoComplete="email"
          label="Email"
          name="email"
          onChange={(event) => setEmail(event.target.value)}
          type="email"
          value={email}
        />
        <ResendVerificationButton email={email} />
      </div>
    </form>
  );
}
