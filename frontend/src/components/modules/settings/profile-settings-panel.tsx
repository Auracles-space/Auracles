"use client";

/**
 * Private profile settings panel.
 *
 * Shows authenticated identity details, current email-verification state, and
 * KYC status using the existing auth/settings endpoints. No new profile-write
 * API is invented here; actionable links route the user to the already-built
 * email, KYC, session, and account settings flows.
 */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import { resendVerificationV1AuthResendVerificationPost } from "@/lib/generated/sdk.gen";
import type { CurrentUserResponse } from "@/lib/generated/types.gen";

import { FormMessage } from "../auth/form-message";

/**
 * Convert backend role slugs into UI-ready labels.
 *
 * @param role - Raw role identifier from auth state.
 */
function formatRoleLabel(role: string): string {
  switch (role) {
    case "admin":
      return "Admin";
    case "attestor":
      return "Attestor";
    case "contributor":
      return "Contributor";
    case "operator":
      return "Operator";
    default:
      return role;
  }
}

/**
 * Derive a concise KYC status label for the private profile page.
 *
 * @param status - Raw KYC status from `/v1/auth/me`.
 */
function formatKycLabel(status: string): string {
  switch (status) {
    case "verified":
      return "Verified";
    case "pending":
      return "Pending review";
    case "rejected":
      return "Rejected";
    default:
      return "Not started";
  }
}

/**
 * Render the private identity, email-verification, and KYC summary page.
 */
export function ProfileSettingsPanel() {
  const [currentUser, setCurrentUser] = useState<CurrentUserResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [resending, setResending] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function loadCurrentUser(): Promise<void> {
      const user = await loadCurrentUserSession();
      if (!mounted) {
        return;
      }

      setLoading(false);
      if (!user) {
        setError("The request could not be completed.");
        return;
      }

      setCurrentUser(user);
    }

    void loadCurrentUser();
    return () => {
      mounted = false;
    };
  }, []);

  const roleLabels = useMemo(
    () => currentUser?.roles.map((role) => formatRoleLabel(role)) ?? [],
    [currentUser?.roles],
  );
  const kycLabel = useMemo(
    () => formatKycLabel(currentUser?.kyc_status ?? "unverified"),
    [currentUser?.kyc_status],
  );

  async function resendVerification(): Promise<void> {
    if (!currentUser?.email) {
      return;
    }

    setResending(true);
    setError(null);
    setMessage(null);
    configureBrowserClient();
    const result = await resendVerificationV1AuthResendVerificationPost({
      body: { email: currentUser.email },
    });
    setResending(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setMessage(result.data?.message ?? "Verification email sent.");
  }

  if (loading) {
    return (
      <div className="rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm text-foreground-muted">
        Loading private profile...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error ? <FormMessage kind="error" message={error} /> : null}
      {message ? <FormMessage kind="success" message={message} /> : null}

      {currentUser ? (
        <>
          <section
            aria-labelledby="private-profile-heading"
            className="rounded-xl border border-border-default bg-surface-2 p-5"
            role="region"
          >
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Private profile
            </p>
            <h2
              className="mt-2 font-heading text-2xl font-bold text-foreground"
              id="private-profile-heading"
            >
              Private profile
            </h2>
            <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <div className="space-y-2">
                <p className="text-lg font-semibold text-foreground">
                  {currentUser.display_name}
                </p>
                <p className="text-sm text-foreground-muted">{currentUser.email}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {roleLabels.map((label) => (
                  <span
                    className="rounded-md border border-border-default bg-background px-2 py-1 text-xs font-medium text-foreground"
                    key={label}
                  >
                    {label}
                  </span>
                ))}
              </div>
            </div>
          </section>

          <section
            aria-labelledby="email-verification-heading"
            className="rounded-xl border border-border-default bg-surface-2 p-5"
            role="region"
          >
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                  Email verification
                </p>
                <h3
                  className="mt-2 font-heading text-xl font-semibold text-foreground"
                  id="email-verification-heading"
                >
                  Email verification
                </h3>
                <p className="mt-2 text-sm leading-6 text-foreground-muted">
                  {currentUser.email_verified
                    ? "Verified and ready for protected account actions."
                    : "Not verified yet. Verify this address before protected account actions."}
                </p>
              </div>
              {currentUser.email_verified ? null : (
                <Button
                  disabled={resending}
                  onClick={() => void resendVerification()}
                  type="button"
                >
                  {resending ? "Sending..." : "Resend verification email"}
                </Button>
              )}
            </div>
          </section>

          <section
            aria-labelledby="kyc-status-heading"
            className="rounded-xl border border-border-default bg-surface-2 p-5"
            role="region"
          >
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                  KYC status
                </p>
                <h3
                  className="mt-2 font-heading text-xl font-semibold text-foreground"
                  id="kyc-status-heading"
                >
                  KYC status
                </h3>
                <p className="mt-2 text-sm leading-6 text-foreground-muted">
                  {kycLabel}
                </p>
              </div>
              <Link
                className="inline-flex min-h-11 items-center justify-center rounded-lg border border-border-default bg-background px-4 py-2 text-sm font-medium text-foreground transition hover:bg-surface-1"
                href="/settings/kyc"
              >
                {currentUser.kyc_status === "verified" ? "Review KYC" : "Continue KYC"}
              </Link>
            </div>
          </section>

          <section
            aria-labelledby="related-account-actions-heading"
            className="rounded-xl border border-border-default bg-surface-2 p-5"
            role="region"
          >
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Related settings
            </p>
            <h3
              className="mt-2 font-heading text-xl font-semibold text-foreground"
              id="related-account-actions-heading"
            >
              Related settings
            </h3>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Link
                className="flex min-h-11 items-center justify-center rounded-lg border border-border-default bg-background px-4 py-2 text-sm font-medium text-foreground transition hover:bg-surface-1"
                href="/settings/account"
              >
                Account and GDPR
              </Link>
              <Link
                className="flex min-h-11 items-center justify-center rounded-lg border border-border-default bg-background px-4 py-2 text-sm font-medium text-foreground transition hover:bg-surface-1"
                href="/settings/sessions"
              >
                Manage sessions
              </Link>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
