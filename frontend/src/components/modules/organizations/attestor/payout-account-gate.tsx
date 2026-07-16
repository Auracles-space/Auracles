"use client";

/**
 * Payout-account gate for the org attestor application checklist.
 *
 * Lets an owner/admin onboard an org-owned payout destination and link it to
 * the live application, satisfying the `payout_account` approval gate. Onboarding
 * and linking both run before the provider redirect, so an abandoned Stripe flow
 * still leaves the gate satisfied. Locked once the application leaves draft/needs_info.
 *
 * Maps to: FR-ATT / org-attestor design step 5 (payout account).
 */

import { useState } from "react";
import {
  onboardOrgPayoutAccount,
  updateOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";

/**
 * Render the payout-account onboarding + link control for the checklist.
 *
 * @param orgId - Organization owning the application.
 * @param application - The live application, or null before it exists.
 * @param onChange - Refetch callback fired after the account links.
 */
export function PayoutAccountGate({
  orgId,
  application,
  onChange,
}: {
  orgId: string;
  application: OrgAttestorApplicationResponse | null;
  onChange: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const linked = Boolean(application?.payout_account_id);
  const canEdit =
    application?.status === "draft" || application?.status === "needs_info";

  /** Onboard a Stripe payout destination, link it, then redirect to setup. */
  async function handleSetup() {
    setLoading(true);
    setError(null);
    try {
      const onboard = await onboardOrgPayoutAccount({
        path: { org_id: orgId },
        body: {
          provider: "stripe",
          refresh_url: window.location.href,
          return_url: window.location.href,
        },
        headers: getAccessTokenHeaders(),
      });
      if (onboard.error || !onboard.data) {
        setError(describeGeneratedError(onboard.error));
        return;
      }

      // Link the account to the application before navigating away: the gate
      // checks payout_account_id, not whether Stripe onboarding finished.
      // Re-onboarding an already-linked account returns the same id, so this
      // is a no-op link on the "continue verification" path.
      const link = await updateOrgAttestorApplication({
        path: { org_id: orgId },
        body: { payout_account_id: onboard.data.payout_account.id },
        headers: getAccessTokenHeaders(),
      });
      if (link.error) {
        setError(describeGeneratedError(link.error));
        return;
      }

      // Redirect to provider verification. Navigate before refetching so the
      // parent re-render can't swap this control out mid-flight. Only fall back
      // to a refetch when the provider returned no onboarding URL.
      if (onboard.data.onboarding_url) {
        window.location.assign(onboard.data.onboarding_url);
        return;
      }
      onChange();
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  if (linked) {
    return (
      <div className="space-y-3">
        {error && (
          <div className="rounded-lg border border-error/50 bg-error/5 p-3 text-sm text-error">
            {error}
          </div>
        )}
        <p className="text-sm font-medium text-success">Payout account linked.</p>
        <p className="text-sm text-foreground-muted">
          This satisfies the payout requirement for your application. You can
          finish or update verification on Stripe anytime before your first
          payout — it reconnects the same account.
        </p>
        <Button
          type="button"
          variant="secondary"
          onClick={handleSetup}
          disabled={loading}
          loading={loading}
        >
          Manage on Stripe
        </Button>
      </div>
    );
  }

  if (!canEdit) {
    return (
      <p className="text-sm text-foreground-muted">
        No payout account is linked to this application.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <div className="rounded-lg border border-error/50 bg-error/5 p-3 text-sm text-error">
          {error}
        </div>
      )}
      <p className="text-sm text-foreground-muted">
        Connect a payout destination so your organization can receive attestation
        earnings. You&apos;ll be redirected to the provider to finish verification.
      </p>
      <Button type="button" onClick={handleSetup} disabled={loading} loading={loading}>
        Set up payout account
      </Button>
    </div>
  );
}
