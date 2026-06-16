"use client";

/**
 * Password reset request form.
 *
 * Mirrors the backend no-enumeration contract by showing the same successful
 * copy regardless of whether an account exists for the submitted address.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { isEmail } from "@/lib/forms/validators";
import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { forgotPassword } from "@/lib/generated/sdk.gen";

import { FormField } from "./form-field";
import { FormMessage } from "./form-message";

/**
 * Render the password reset request form.
 */
export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const canSubmit = isEmail(email);

  async function submitResetRequest(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsSubmitting(true);
    configureBrowserClient();

    const result = await forgotPassword({ body: { email: email.trim() } });
    setIsSubmitting(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSuccess(result.data?.message ?? "If email is valid, reset link sent.");
  }

  return (
    <form className="space-y-5" onSubmit={submitResetRequest}>
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Reset password
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          We will send a time-limited reset link if the address is registered.
        </p>
      </div>
      {error ? <FormMessage kind="error" message={error} /> : null}
      {success ? <FormMessage kind="success" message={success} /> : null}
      <FormField
        autoComplete="email"
        label="Email"
        name="email"
        onChange={(event) => setEmail(event.target.value)}
        required
        type="email"
        value={email}
      />
      <Button className="w-full" disabled={isSubmitting || !canSubmit} type="submit">
        {isSubmitting ? "Sending link" : "Send reset link"}
      </Button>
    </form>
  );
}
