"use client";

/**
 * Registration form for email/password accounts.
 *
 * Implements FR-AUTH-001 and FR-AUTH-003 from the frontend side. Submission
 * uses only the generated OpenAPI client; backend validation remains the
 * authority for password policy and role eligibility.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { registerUser } from "@/lib/generated/sdk.gen";

import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import {
  allValid,
  isEmail,
  isNonEmpty,
  meetsPasswordPolicy,
  passwordsMatch,
} from "@/lib/forms/validators";
import { FormField } from "./form-field";
import { FormMessage } from "./form-message";
import { AuthDivider, GoogleSignInButton } from "./google-sign-in-button";
import { ResendVerificationButton } from "./resend-verification-button";

type AssignableRole = "contributor" | "operator";

const roleOptions: Array<{ description: string; label: string; value: AssignableRole }> =
  [
    {
      description: "Package professional expertise into licensed frameworks.",
      label: "Contributor",
      value: "contributor",
    },
    {
      description: "Purchase frameworks and manage implementation work.",
      label: "Operator",
      value: "operator",
    },
  ];

/**
 * Render the account creation form and submit valid payloads to the API.
 */
export function RegisterForm() {
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [roles, setRoles] = useState<AssignableRole[]>([]);
  const [success, setSuccess] = useState<string | null>(null);

  function toggleRole(role: AssignableRole): void {
    setRoles((current) => {
      if (current.includes(role)) {
        return current.filter((value) => value !== role);
      }
      return [...current, role];
    });
  }

  const canSubmit = allValid(
    isNonEmpty(displayName),
    isEmail(email),
    meetsPasswordPolicy(password),
    passwordsMatch(password, confirmPassword),
    roles.length > 0,
    agreedToTerms,
  );

  async function submitRegistration(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    if (roles.length === 0) {
      setError("Select at least one role.");
      return;
    }

    if (!agreedToTerms) {
      setError("You must agree to the Terms of Service and Privacy Policy.");
      return;
    }

    setIsSubmitting(true);
    configureBrowserClient();
    const result = await registerUser({
      body: {
        display_name: displayName.trim(),
        email: email.trim(),
        password,
        roles,
      },
    });
    setIsSubmitting(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSuccess(
      result.data?.message ??
        "We've sent a verification link to your email. Please check your inbox to activate your account.",
    );
  }

  if (success) {
    return (
      <div className="space-y-5">
        <div>
          <h2 className="font-heading text-xl font-semibold text-foreground">
            Check your inbox
          </h2>
          <p className="mt-2 text-sm leading-6 text-foreground-muted">
            We&apos;ve sent a verification link to{" "}
            <span className="font-medium text-foreground">{email}</span>. Click
            the link in that email to activate your account.
          </p>
        </div>
        <ResendVerificationButton email={email} />
        <p className="text-sm leading-6 text-foreground-muted">
          Prefer to enter the token manually?{" "}
          <a
            className="font-medium text-accent hover:underline"
            href="/verify-email"
          >
            Go to verification
          </a>
          .
        </p>
      </div>
    );
  }

  return (
    <form className="space-y-5" onSubmit={submitRegistration}>
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Create account
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Choose the role that matches how you will use Auracles.
        </p>
      </div>

      {error ? <FormMessage kind="error" message={error} /> : null}
      {success ? <FormMessage kind="success" message={success} /> : null}

      <div className="space-y-2">
        <GoogleSignInButton label="Sign up with Google" />
        <p className="text-xs leading-5 text-foreground-subtle">
          By signing up with Google you agree to our{" "}
          <a className="font-medium text-accent hover:underline" href="/terms" target="_blank" rel="noreferrer">
            Terms
          </a>{" "}
          and{" "}
          <a className="font-medium text-accent hover:underline" href="/privacy" target="_blank" rel="noreferrer">
            Privacy Policy
          </a>
          . You&apos;ll pick how you use Auracles right after.
        </p>
      </div>
      <AuthDivider />

      <FormField
        autoFocus
        autoComplete="name"
        label="Display name"
        name="display_name"
        onChange={(event) => {
          setDisplayName(event.target.value);
          if (error) setError(null);
        }}
        required
        value={displayName}
        isValid={isNonEmpty(displayName)}
      />
      <FormField
        autoComplete="email"
        label="Email"
        name="email"
        onChange={(event) => {
          setEmail(event.target.value);
          if (error) setError(null);
        }}
        required
        type="email"
        value={email}
        isValid={isEmail(email)}
      />
      <FormField
        autoComplete="new-password"
        helper="Use at least 12 characters with a mix of letters, numbers, and symbols."
        label="Password"
        name="password"
        onChange={(event) => {
          setPassword(event.target.value);
          if (error) setError(null);
        }}
        required
        type="password"
        value={password}
        isValid={meetsPasswordPolicy(password)}
      />
      <FormField
        autoComplete="new-password"
        error={
          confirmPassword.length > 0 &&
          !passwordsMatch(password, confirmPassword)
            ? "Passwords do not match."
            : undefined
        }
        label="Confirm password"
        name="confirm_password"
        onChange={(event) => {
          setConfirmPassword(event.target.value);
          if (error) setError(null);
        }}
        required
        type="password"
        value={confirmPassword}
        isValid={confirmPassword.length > 0 && passwordsMatch(password, confirmPassword)}
      />

      <fieldset className="space-y-3">
        <legend className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          <span>Account role</span>
          {roles.length > 0 && (
            <svg className="h-4 w-4 text-success shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" data-testid="role-checkmark">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
            </svg>
          )}
        </legend>
        <p className="text-xs leading-5 text-foreground-muted">
          Operator and Contributor can be combined. Attestor access is granted
          through an organization, not selected here.
        </p>
        {roleOptions.map((role) => {
          const isSelected = roles.includes(role.value);
          return (
            <label
              className={`flex min-h-12 cursor-pointer gap-3 rounded-xl border p-4 transition ${
                isSelected
                  ? "border-accent bg-surface-1"
                  : "border-border-strong bg-surface-2 hover:border-accent/40"
              }`}
              htmlFor={`role-${role.value}`}
              key={role.value}
            >
              <input
                checked={isSelected}
                className="mt-1 h-4 w-4 accent-accent"
                id={`role-${role.value}`}
                onChange={() => {
                  toggleRole(role.value);
                  if (error) setError(null);
                }}
                type="checkbox"
              />
              <span>
                <span className="block text-sm font-semibold text-foreground">
                  {role.label}
                </span>
                <span className="mt-1 block text-xs leading-5 text-foreground-muted">
                  {role.description}
                </span>
              </span>
            </label>
          );
        })}
      </fieldset>

      <div className="flex min-h-12 items-start gap-3 rounded-xl bg-surface-2 p-3">
        <input
          checked={agreedToTerms}
          className="mt-1 h-4 w-4 accent-accent"
          id="terms-agreement"
          onChange={(e) => {
            setAgreedToTerms(e.target.checked);
            if (error) setError(null);
          }}
          type="checkbox"
        />
        <label className="flex items-start gap-1.5 text-sm leading-5 text-foreground-muted" htmlFor="terms-agreement">
          <span>
            I agree to the{" "}
            <a className="font-medium text-accent hover:underline" href="/terms" target="_blank" rel="noreferrer">
              Terms of Service
            </a>{" "}
            and{" "}
            <a className="font-medium text-accent hover:underline" href="/privacy" target="_blank" rel="noreferrer">
              Privacy Policy
            </a>
            .
          </span>
          {agreedToTerms && (
            <svg className="h-4 w-4 text-success shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" data-testid="terms-checkmark">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
            </svg>
          )}
        </label>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mt-4">
        <a className="text-sm font-medium text-accent hover:underline" href="/login">
          Already have an account? Log in
        </a>
        <Button className="w-full sm:w-auto" disabled={!canSubmit} loading={isSubmitting} type="submit">
          Create account
        </Button>
      </div>
    </form>
  );
}
