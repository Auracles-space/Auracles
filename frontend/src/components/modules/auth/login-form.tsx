"use client";

/**
 * Login form for the browser-session auth contract.
 *
 * Successful non-2FA login stores the access token in memory only. When the
 * backend returns a 2FA challenge, the form moves the user to the challenge
 * step without storing any token or assuming a session exists.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { allValid, isEmail, isNonEmpty } from "@/lib/forms/validators";
import {
  authTokenStore,
  setAccessTokenFromJwt,
} from "@/lib/auth/token-store";
import { getOnboardingDestination } from "@/lib/auth/onboarding";
import { getRoleLandingPath } from "@/lib/auth/route-guards";
import { safeInternalPath } from "@/lib/url/safe-href";
import { getCurrentUser, login } from "@/lib/generated/sdk.gen";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { FormField } from "./form-field";
import { FormMessage } from "./form-message";

type LoginFormProps = {
  next?: string;
  onAuthenticated?: (location: string) => void;
  onChallenge?: (challengeToken: string) => void;
};

/**
 * Render the email/password login form and handle token or 2FA responses.
 *
 * @param props - Resume-intent path plus optional navigation callbacks.
 */
export function LoginForm({ next, onAuthenticated, onChallenge }: LoginFormProps) {
  const safeNext = safeInternalPath(next);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [password, setPassword] = useState("");
  const canSubmit = allValid(isEmail(email), isNonEmpty(password));

  function navigateTo(location: string): void {
    if (onAuthenticated) {
      onAuthenticated(location);
      return;
    }
    window.location.assign(location);
  }

  function navigateToChallenge(challengeToken: string): void {
    if (onChallenge) {
      onChallenge(challengeToken);
      return;
    }
    const nextParam = safeNext ? `&next=${encodeURIComponent(safeNext)}` : "";
    window.location.assign(
      `/2fa-challenge?challenge=${encodeURIComponent(challengeToken)}${nextParam}`,
    );
  }

  async function submitLogin(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    configureBrowserClient();

    const result = await login({
      body: {
        email: email.trim(),
        password,
      },
    });
    setIsSubmitting(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    if (result.data?.requires_2fa && result.data.challenge_token) {
      navigateToChallenge(result.data.challenge_token);
      return;
    }

    if (!result.data?.access_token) {
      setError("Login succeeded without an access token.");
      return;
    }

    setAccessTokenFromJwt(result.data.access_token);
    const roleLandingPath = getRoleLandingPath(authTokenStore.getState().roles);
    const currentUser = await getCurrentUser({
      headers: getAccessTokenHeaders(),
    });

    if (!currentUser.response.ok || !currentUser.data) {
      navigateTo(safeNext ?? roleLandingPath);
      return;
    }

    const onboardingDestination = getOnboardingDestination(
      currentUser.data,
      roleLandingPath,
    );
    // Honor the resume-intent target only when the account is fully onboarded;
    // otherwise the onboarding gate takes precedence.
    navigateTo(
      onboardingDestination === roleLandingPath
        ? safeNext ?? roleLandingPath
        : onboardingDestination,
    );
  }

  return (
    <form className="space-y-5" onSubmit={submitLogin}>
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Log in
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Access your workspace with your verified email address.
        </p>
      </div>

      {error ? <FormMessage kind="error" message={error} /> : null}

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
        autoComplete="current-password"
        label="Password"
        name="password"
        onChange={(event) => setPassword(event.target.value)}
        required
        type="password"
        value={password}
      />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <a className="text-sm font-medium text-accent hover:underline" href="/forgot-password">
            Reset password
          </a>
          <span className="text-sm text-foreground-subtle">•</span>
          <a className="text-sm font-medium text-accent hover:underline" href="/register">
            Sign up
          </a>
        </div>
        <Button disabled={isSubmitting || !canSubmit} type="submit">
          {isSubmitting ? "Logging in" : "Log in"}
        </Button>
      </div>
    </form>
  );
}
