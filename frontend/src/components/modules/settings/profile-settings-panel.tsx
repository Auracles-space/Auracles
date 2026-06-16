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

type UserRole = "admin" | "attestor" | "contributor" | "operator";

/**
 * Render a styled role badge with an inline SVG icon.
 *
 * @param props - Raw role identifier.
 */
function RoleBadge({ role }: { role: string }) {
  const normalized = role.toLowerCase() as UserRole;
  
  let styles = "bg-foreground/5 border-border-default text-foreground-muted";
  let icon = null;
  let label = role;

  if (normalized === "admin") {
    styles = "bg-accent/10 border-accent/20 text-accent";
    label = "Admin";
    icon = (
      <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    );
  } else if (normalized === "attestor") {
    styles = "bg-info/10 border-info/20 text-info";
    label = "Attestor";
    icon = (
      <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
      </svg>
    );
  } else if (normalized === "contributor") {
    styles = "bg-success/10 border-success/20 text-success";
    label = "Contributor";
    icon = (
      <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
      </svg>
    );
  } else if (normalized === "operator") {
    styles = "bg-warning/10 border-warning/20 text-warning";
    label = "Operator";
    icon = (
      <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    );
  }

  return (
    <span
      className={`inline-flex h-7 items-center gap-1.5 rounded-badge border px-2.5 text-xs font-medium uppercase tracking-[0.05em] ${styles}`}
    >
      {icon}
      {label}
    </span>
  );
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
              <div className="flex flex-wrap gap-2 items-start md:justify-end">
                {currentUser.roles.map((role) => (
                  <RoleBadge key={role} role={role} />
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
