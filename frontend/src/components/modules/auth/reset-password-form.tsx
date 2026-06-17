"use client";

/**
 * Password reset completion form.
 *
 * Sends the single-use reset token and new password through the generated
 * client. The backend enforces expiry, token use, and password strength.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  allValid,
  isNonEmpty,
  isPasswordLongEnough,
  passwordsMatch,
} from "@/lib/forms/validators";
import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { resetPassword } from "@/lib/generated/sdk.gen";

import { FormField } from "./form-field";
import { FormMessage } from "./form-message";

type ResetPasswordFormProps = {
  initialToken?: string;
  onReset?: (location: string) => void;
};

/**
 * Render the password reset completion form.
 *
 * @param props - Optional token captured from search params, and an optional
 *   navigation callback (injected in tests; defaults to a hard redirect).
 */
export function ResetPasswordForm({
  initialToken = "",
  onReset,
}: ResetPasswordFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [success, setSuccess] = useState<string | null>(null);
  const [token, setToken] = useState(initialToken);
  const canSubmit = allValid(
    isNonEmpty(token),
    isPasswordLongEnough(newPassword),
    passwordsMatch(newPassword, confirmPassword),
  );

  async function submitReset(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsSubmitting(true);
    configureBrowserClient();

    const result = await resetPassword({
      body: { new_password: newPassword, token: token.trim() },
    });
    setIsSubmitting(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSuccess(result.data?.message ?? "Password reset.");
    // Hard navigation re-runs auth middleware (matches verify-email-form).
    if (onReset) {
      onReset("/login");
      return;
    }
    window.location.assign("/login");
  }

  return (
    <form className="space-y-5" onSubmit={submitReset}>
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Set new password
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Use the reset token from your email and choose a stronger password.
        </p>
      </div>
      {error ? <FormMessage kind="error" message={error} /> : null}
      {success ? <FormMessage kind="success" message={success} /> : null}
      <FormField
        label="Reset token"
        name="token"
        onChange={(event) => setToken(event.target.value)}
        required
        value={token}
      />
      <FormField
        autoComplete="new-password"
        helper="Use at least 12 characters with a mix of letters, numbers, and symbols."
        label="New password"
        name="new_password"
        onChange={(event) => setNewPassword(event.target.value)}
        required
        type="password"
        value={newPassword}
      />
      <FormField
        autoComplete="new-password"
        error={
          confirmPassword.length > 0 &&
          !passwordsMatch(newPassword, confirmPassword)
            ? "Passwords do not match."
            : undefined
        }
        label="Confirm password"
        name="confirm_password"
        onChange={(event) => setConfirmPassword(event.target.value)}
        required
        type="password"
        value={confirmPassword}
      />
      <Button className="w-full" disabled={isSubmitting || !canSubmit} type="submit">
        {isSubmitting ? "Saving password" : "Save password"}
      </Button>
    </form>
  );
}
