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
import { FormField } from "./form-field";
import { FormMessage } from "./form-message";

type AssignableRole = "attestor" | "contributor" | "operator";

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
    {
      description: "Verify framework quality after admin approval.",
      label: "Attestor",
      value: "attestor",
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

    setSuccess(result.data?.message ?? "Verification sent.");
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

      <FormField
        autoComplete="name"
        label="Display name"
        name="display_name"
        onChange={(event) => setDisplayName(event.target.value)}
        required
        value={displayName}
      />
      <FormField
        autoComplete="email"
        label="Email"
        name="email"
        onChange={(event) => setEmail(event.target.value)}
        required
        type="email"
        value={email}
      />
      <FormField
        autoComplete="new-password"
        helper="Use at least 12 characters with a mix of letters, numbers, and symbols."
        label="Password"
        name="password"
        onChange={(event) => setPassword(event.target.value)}
        required
        type="password"
        value={password}
      />

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium text-foreground">
          Account role
        </legend>
        {roleOptions.map((role) => (
          <label
            className="flex min-h-12 cursor-pointer gap-3 rounded-card border border-border-strong bg-surface-2 p-4 transition hover:border-accent/40 shadow-sm"
            htmlFor={`role-${role.value}`}
            key={role.value}
          >
            <input
              checked={roles.includes(role.value)}
              className="mt-1 h-4 w-4 accent-accent"
              id={`role-${role.value}`}
              onChange={() => toggleRole(role.value)}
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
        ))}
      </fieldset>

      <div className="flex items-start gap-3 py-2">
        <input
          checked={agreedToTerms}
          className="mt-0.5 h-4 w-4 accent-accent"
          id="terms-agreement"
          onChange={(e) => setAgreedToTerms(e.target.checked)}
          type="checkbox"
        />
        <label className="text-sm leading-5 text-foreground-muted" htmlFor="terms-agreement">
          I agree to the{" "}
          <a className="font-medium text-accent hover:underline" href="/terms" target="_blank" rel="noreferrer">
            Terms of Service
          </a>{" "}
          and{" "}
          <a className="font-medium text-accent hover:underline" href="/privacy" target="_blank" rel="noreferrer">
            Privacy Policy
          </a>
          .
        </label>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mt-4">
        <a className="text-sm font-medium text-accent hover:underline" href="/login">
          Already have an account? Log in
        </a>
        <Button className="w-full sm:w-auto" disabled={isSubmitting} type="submit">
          {isSubmitting ? "Creating account" : "Create account"}
        </Button>
      </div>
    </form>
  );
}
