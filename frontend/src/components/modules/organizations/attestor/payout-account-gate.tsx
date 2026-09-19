"use client";

/**
 * Payout-account gate for the org attestor application checklist.
 *
 * Lets an owner/admin onboard an org-owned payout destination and link it to
 * the live application, satisfying the `payout_account` approval gate. Onboarding
 * and linking both run before the provider redirect, so an abandoned Stripe flow
 * still leaves the gate satisfied. Locked once the application leaves draft/needs_info.
 *
 * Which rail is used follows the deployment, not the caller: on an NGN
 * deployment Stripe Connect cannot pay out at all, so the org's bank details
 * are collected here and registered with Paystack instead of redirecting.
 *
 * On that rail the holder's name is shown for acceptance first. Registering
 * an account here also links it to the application, so a mistyped number
 * would satisfy the approval gate with a stranger's bank account — and this
 * is the surface an applicant reaches before any payout settings page.
 *
 * Maps to: FR-ATT / org-attestor design step 5 (payout account).
 */

import { useCallback, useState } from "react";
import {
  onboardOrgPayoutAccount,
  resolveOrgPayoutAccountName,
  updateOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import {
  type BankDetails,
  ConfirmBankAccount,
  type ResolveResult,
} from "@/components/modules/financials/confirm-bank-account";
import { payoutProviderForCountry } from "@/lib/marketplace/currency";

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

  // The org's own country is not loaded here, but it does not need to be: on an
  // NGN deployment every country settles through Paystack, and on a USD one an
  // org reaching this gate is a Connect country by construction.
  const isPaystackRail = payoutProviderForCountry("") === "paystack";

  const linked = Boolean(application?.payout_account_id);
  const canEdit =
    application?.status === "draft" || application?.status === "needs_info";

  /** Ask the bank who holds an account, registering nothing. */
  const resolveAccount = useCallback(
    async ({ accountNumber, bankCode }: BankDetails): Promise<ResolveResult> => {
      configureBrowserClient();
      const result = await resolveOrgPayoutAccountName({
        path: { org_id: orgId },
        body: { account_number: accountNumber, bank_code: bankCode },
        headers: getAccessTokenHeaders(),
      });
      if (result.error || !result.data) {
        return { error: describeGeneratedError(result.error) };
      }
      return { name: result.data.account_name };
    },
    [orgId],
  );

  /** Register and link the account once its holder has been accepted. */
  const confirmAccount = useCallback(
    (details: BankDetails) => handleSetup(details),
    // handleSetup closes over orgId and onChange, both stable for a render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [orgId, onChange],
  );

  /** Onboard an org payout destination on its rail, then link it. */
  async function handleSetup(
    details?: BankDetails,
  ): Promise<{ error: string } | null> {
    setLoading(true);
    setError(null);
    try {
      // Installs the step-up and refresh interceptors, so a 403 step-up
      // refusal prompts for 2FA instead of dead-ending on this form.
      configureBrowserClient();
      const onboard = await onboardOrgPayoutAccount({
        path: { org_id: orgId },
        body: details
          ? {
              account_number: details.accountNumber,
              bank_code: details.bankCode,
              provider: "paystack" as const,
            }
          : {
              provider: "stripe" as const,
              refresh_url: window.location.href,
              return_url: window.location.href,
            },
        headers: getAccessTokenHeaders(),
      });
      if (onboard.error || !onboard.data) {
        const message = describeGeneratedError(onboard.error);
        setError(message);
        return { error: message };
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
        const message = describeGeneratedError(link.error);
        setError(message);
        return { error: message };
      }

      // Redirect to provider verification. Navigate before refetching so the
      // parent re-render can't swap this control out mid-flight. Only fall back
      // to a refetch when the provider returned no onboarding URL.
      if (onboard.data.onboarding_url) {
        window.location.assign(onboard.data.onboarding_url);
        return null;
      }
      onChange();
      return null;
    } catch (caught) {
      const message = describeGeneratedError(caught);
      setError(message);
      return { error: message };
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
          {isPaystackRail
            ? "This satisfies the payout requirement for your application. Payouts are sent straight to this bank account."
            : "This satisfies the payout requirement for your application. You can finish or update verification on Stripe anytime before your first payout — it reconnects the same account."}
        </p>
        {isPaystackRail ? null : (
          <Button
            type="button"
            variant="secondary"
            onClick={handleSetup}
            disabled={loading}
            loading={loading}
          >
            Manage on Stripe
          </Button>
        )}
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
        {isPaystackRail
          ? "Add the bank account your organization's attestation earnings should be paid into."
          : "Connect a payout destination so your organization can receive attestation earnings. You'll be redirected to the provider to finish verification."}
      </p>
      {isPaystackRail ? (
        <ConfirmBankAccount
          confirmLabel="Yes, use this account"
          idPrefix="org-attestor-payout"
          onConfirm={confirmAccount}
          resolve={resolveAccount}
        />
      ) : (
        <Button
          type="button"
          onClick={() => void handleSetup()}
          disabled={loading}
          loading={loading}
        >
          Set up payout account
        </Button>
      )}
    </div>
  );
}
