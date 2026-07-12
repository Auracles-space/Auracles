"use client";

/**
 * Identity verification panel.
 *
 * Launches the Persona hosted verification flow: requests a one-time session
 * link from the backend, then sends the user to Persona to complete the check.
 * The decision arrives asynchronously via webhook and updates kyc_status, so
 * the panel re-reads status when the user tabs back. Documents are held by
 * Persona — never uploaded to or stored by Auracles.
 *
 * Maps to: FR-AUTH KYC, identity verification design (2026-06-24).
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ensureBrowserAccessToken } from "@/lib/auth/current-user-session";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getKycStatusV1SettingsKycGet as getKycStatus,
  startIdentityVerificationV1SettingsKycSessionPost as startVerificationSession,
  syncKycFromReturnV1SettingsKycSyncPost as syncKycFromReturn,
} from "@/lib/generated/sdk.gen";

import { FormMessage } from "./form-message";

/**
 * Render the authenticated identity-verification workflow.
 */
export function KycUpload() {
  const [kycStatus, setKycStatus] = useState<string>("unverified");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isStarting, setIsStarting] = useState(false);

  const fetchStatus = useCallback(async () => {
    configureBrowserClient();
    // After a page reload the access token is gone (memory-only); rehydrate it
    // from the refresh cookie before calling the API, or the status read 401s.
    const hasToken = await ensureBrowserAccessToken();
    if (!hasToken) {
      setIsLoading(false);
      return;
    }
    try {
      const response = await getKycStatus({ headers: getAccessTokenHeaders() });
      if (response.response.ok && response.data) {
        setKycStatus(response.data.kyc_status);
      }
    } catch {
      console.error("Failed to load verification status");
    } finally {
      setIsLoading(false);
    }
  }, []);

  // On return from the hosted flow, Persona appends ?inquiry-id=... to the URL.
  // The redirect carries no trusted verdict, so read the decision server-to-
  // server (which applies it) instead of showing a stale pending state while
  // waiting for the async webhook. Falls back to a plain status read.
  const initStatus = useCallback(async () => {
    const inquiryId = new URLSearchParams(window.location.search).get(
      "inquiry-id",
    );
    if (!inquiryId) {
      await fetchStatus();
      return;
    }
    configureBrowserClient();
    const hasToken = await ensureBrowserAccessToken();
    if (!hasToken) {
      setIsLoading(false);
      return;
    }
    try {
      const response = await syncKycFromReturn({
        headers: getAccessTokenHeaders(),
        body: { inquiry_id: inquiryId },
      });
      if (response.response.ok && response.data) {
        setKycStatus(response.data.kyc_status);
      } else {
        // Sync failed (e.g. unknown inquiry) — fall back to the current status
        // so the panel still reflects server truth rather than a dead spinner.
        await fetchStatus();
      }
    } catch {
      await fetchStatus();
    } finally {
      // Strip the inquiry id so a refresh does not re-sync a consumed inquiry.
      window.history.replaceState({}, "", window.location.pathname);
      setIsLoading(false);
    }
  }, [fetchStatus]);

  useEffect(() => {
    initStatus();
  }, [initStatus]);

  // The decision is asynchronous (Persona webhook -> kyc_status). The user
  // leaves to Persona and tabs back, so re-read on focus / visibility to show
  // the verdict without a manual refresh — a once-changing value needs no socket.
  useEffect(() => {
    function refetchOnReturn() {
      if (document.visibilityState === "visible") {
        fetchStatus();
      }
    }
    window.addEventListener("focus", refetchOnReturn);
    document.addEventListener("visibilitychange", refetchOnReturn);
    return () => {
      window.removeEventListener("focus", refetchOnReturn);
      document.removeEventListener("visibilitychange", refetchOnReturn);
    };
  }, [fetchStatus]);

  async function startVerification(): Promise<void> {
    setError(null);
    setIsStarting(true);
    configureBrowserClient();
    await ensureBrowserAccessToken();
    try {
      const session = await startVerificationSession({
        headers: getAccessTokenHeaders(),
      });
      if (!session.response.ok || !session.data) {
        setIsStarting(false);
        setError(describeGeneratedError(session.error));
        return;
      }
      // Hand off to Persona's hosted flow. The webhook flips kyc_status; the
      // user returns to this page where the focus refetch surfaces the verdict.
      window.location.assign(session.data.hosted_url);
    } catch {
      setIsStarting(false);
      setError("We couldn't start verification. Try again in a moment.");
    }
  }

  if (isLoading) {
    return (
      <div
        className="flex min-h-[200px] flex-col items-center justify-center space-y-3"
        data-testid="loading"
      >
        <svg className="h-8 w-8 animate-spin text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        <span className="text-sm font-medium text-foreground-muted">Loading verification status...</span>
      </div>
    );
  }

  const isRejected = kycStatus === "rejected";
  const canStart = kycStatus !== "verified" && kycStatus !== "pending";

  return (
    <div className="space-y-6">
      {kycStatus === "verified" && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-success/30 bg-success/5 p-6 text-center space-y-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-success text-white shadow-sm">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Identity Verified</h3>
            <p className="text-sm text-foreground-muted max-w-md">
              Your identity is verified. Your account is fully eligible to publish licensed Frameworks and request payouts.
            </p>
          </div>
        </div>
      )}

      {kycStatus === "pending" && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-warning/30 bg-warning/5 p-6 text-center space-y-3 animate-pulse">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-warning text-white shadow-sm">
            <svg className="h-6 w-6 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Verification Pending</h3>
            <p className="text-sm text-foreground-muted max-w-md">
              We&apos;re confirming your identity with our verification partner. This usually takes a minute. We&apos;ll notify you the moment it&apos;s done.
            </p>
          </div>
          {/* A dropped or abandoned hosted flow leaves the user pending until a
              webhook that may never arrive — always offer a restart so they are
              never locked out. Backend allows pending -> a fresh inquiry. */}
          <div className="w-full max-w-md space-y-3 pt-1">
            {error ? <FormMessage kind="error" message={error} /> : null}
            <p className="text-xs text-foreground-muted">
              Didn&apos;t finish, or taking too long?
            </p>
            <Button
              className="w-full"
              disabled={isStarting}
              onClick={startVerification}
              type="button"
              variant="secondary"
            >
              {isStarting ? "Opening secure check…" : "Restart verification"}
            </Button>
          </div>
        </div>
      )}

      {isRejected && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-error/30 bg-error/5 p-6 text-center space-y-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-error text-white shadow-sm">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Verification Didn&apos;t Pass</h3>
            <p className="text-sm text-foreground-muted max-w-md">
              We couldn&apos;t confirm your identity from the last check. Make sure your ID is clear and well-lit, then try again.
            </p>
          </div>
        </div>
      )}

      {canStart && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border-default bg-surface-2 p-6 text-center space-y-4">
          {error ? <FormMessage kind="error" message={error} /> : null}
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent/10 text-accent">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">
              {isRejected ? "Try verification again" : "Verify your identity"}
            </h3>
            <p className="text-sm text-foreground-muted max-w-md">
              A quick, secure check by our verification partner. Have a government ID ready — it takes about two minutes. Your documents go to Persona, never stored on Auracles.
            </p>
          </div>
          <Button className="w-full" disabled={isStarting} onClick={startVerification} type="button">
            {isStarting ? "Opening secure check…" : isRejected ? "Try again" : "Verify identity"}
          </Button>
        </div>
      )}
    </div>
  );
}
