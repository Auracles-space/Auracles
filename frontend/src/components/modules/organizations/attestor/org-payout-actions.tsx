"use client";

/**
 * Payout Actions panel for an attestor organization.
 *
 * Gates on the attestor application: until it is approved only its status is
 * shown; once approved without a payout account, an org admin links one
 * (Paystack bank details on the NGN rail, Stripe Connect onboarding
 * elsewhere); with an account linked, the request controls take over.
 * Requesting a payout needs a step-up 2FA window, which the global step-up
 * prompt handles when the API refuses.
 *
 * Maps to: FR-FIN-* (organization payouts).
 */
import { useState } from "react";

import {
  onboardOrgPayoutAccount,
  requestOrgPayout,
  resolveOrgPayoutAccountName,
} from "@/lib/generated/sdk.gen";
import type {
  OrgAttestorApplicationResponse,
  OrgEarningsResponse,
} from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import {
  ConfirmBankAccount,
  type BankDetails,
} from "@/components/modules/financials/confirm-bank-account";
import { payoutProviderForCountry } from "@/lib/marketplace/currency";
import { formatMoney } from "@/lib/marketplace/format";
import { ownerStatusKey, StatusPill } from "@/components/ui/status-pill";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

import { OrgPayoutRequestControls } from "./org-payout-request-controls";

interface OrgPayoutActionsProps {
  /** Organization whose payout account and payouts are managed. */
  orgId: string;
  /** Whether the viewer owns the organization. */
  isOwner: boolean;
  /** Earnings response, or null when it failed to load. */
  earnings: OrgEarningsResponse | null;
  /** Attestor application, or null when the org has none. */
  application: OrgAttestorApplicationResponse | null;
  /** Reload earnings and application after an action changes them. */
  onRefresh: () => Promise<void>;
}

/**
 * Render payout account setup and payout request actions.
 *
 * @param props - Org, viewer role, loaded financial data, and refresh hook.
 */
export function OrgPayoutActions({
  orgId,
  isOwner,
  earnings,
  application,
  onRefresh,
}: OrgPayoutActionsProps) {
  const [isActionLoading, setIsActionLoading] = useState(false);

  // Mirrors the backend routing. On an NGN deployment Stripe Connect cannot pay
  // out at all, so bank details are collected here instead of redirecting.
  const isPaystackRail = payoutProviderForCountry("") === "paystack";
  const [payoutError, setPayoutError] = useState<string | null>(null);
  // Confirms a payout that just went through. Without it the refreshed
  // eligibility checklist ("a payout is already in progress") was the only
  // feedback and read as a refusal.
  const [payoutNotice, setPayoutNotice] = useState<string | null>(null);

  /** Look up the account holder's name, registering nothing. */
  const resolveAccount = async (details: BankDetails) => {
    configureBrowserClient();
    const result = await resolveOrgPayoutAccountName({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId },
      body: {
        account_number: details.accountNumber,
        bank_code: details.bankCode,
      },
    });
    if (result.error || !result.data) {
      return { error: describeGeneratedError(result.error) };
    }
    return { name: result.data.account_name };
  };

  /** Register the bank account whose holder has just been accepted. */
  const connectPaystackAccount = async (details: BankDetails) => {
    configureBrowserClient();
    const res = await onboardOrgPayoutAccount({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId },
      body: {
        account_number: details.accountNumber,
        bank_code: details.bankCode,
        provider: "paystack" as const,
      },
    });
    if (!res.data) {
      return { error: describeGeneratedError(res.error) };
    }
    await onRefresh();
    return null;
  };

  /** Send an org owner to Stripe's hosted onboarding. */
  const handleSetupPayoutAccount = async () => {
    setIsActionLoading(true);
    setPayoutError(null);
    try {
      configureBrowserClient();
      const res = await onboardOrgPayoutAccount({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
        body: {
          provider: "stripe" as const,
          refresh_url: window.location.href,
          return_url: window.location.href,
        },
      });
      if (res.data?.onboarding_url) {
        window.location.href = res.data.onboarding_url;
        return;
      }
      if (res.data) {
        await onRefresh();
        return;
      }
      // Non-2xx responses resolve with `error` (the generated client does not
      // throw); surface the reason instead of failing silently.
      setPayoutError(describeGeneratedError(res.error));
    } catch (error) {
      console.error("Failed to onboard payout account:", error);
      setPayoutError("The request could not be completed.");
    } finally {
      setIsActionLoading(false);
    }
  };

  const handleRequestPayout = async () => {
    if (!earnings || !application?.payout_account_id) return;
    setIsActionLoading(true);
    setPayoutError(null);
    setPayoutNotice(null);
    const requestedAmount = formatMoney(earnings.available_balance, earnings.currency);
    try {
      configureBrowserClient();
      const res = await requestOrgPayout({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
        body: {
          amount: earnings.available_balance,
          currency: earnings.currency,
          payout_account_id: application.payout_account_id,
        },
      });
      if (!res.response.ok || !res.data) {
        // Non-2xx responses resolve with `error` (the generated client does not
        // throw); surface the reason instead of failing silently.
        setPayoutError(describeGeneratedError(res.error));
        return;
      }
      setPayoutNotice(
        `Payout of ${requestedAmount} requested. It is on its way to your payout account; the history below shows when it is paid.`,
      );
      await onRefresh(); // Refresh data
    } catch (error) {
      console.error("Failed to request payout:", error);
      setPayoutError("The request could not be completed.");
    } finally {
      setIsActionLoading(false);
    }
  };

  return (
    <div className="p-6 rounded-lg bg-surface-2 border border-border-strong">
      <h3 className="text-lg font-medium mb-4">Payout Actions</h3>
      {payoutError && (
        <p className="text-sm text-error mb-4" role="alert">
          {payoutError}
        </p>
      )}
      {payoutNotice && (
        <p
          className="mb-4 rounded-xl border border-success/30 bg-success/10 p-3 text-sm text-foreground"
          role="status"
        >
          {payoutNotice}
        </p>
      )}
      {application?.status !== "approved" ? (
        <div className="grid justify-items-start gap-2 text-sm text-foreground-subtle">
          {application ? (
            <StatusPill status={ownerStatusKey(application.status, "application")} />
          ) : null}
          <p>Your application must be approved before you can setup payouts.</p>
        </div>
      ) : !application.payout_account_id ? (
        <div>
          <p className="text-sm text-foreground-subtle mb-4">
            You need to configure a payout account to receive earnings.
          </p>
          {isPaystackRail ? (
            <ConfirmBankAccount
              confirmLabel="Yes, use this account"
              idPrefix="org-financials-payout"
              onConfirm={connectPaystackAccount}
              resolve={resolveAccount}
            />
          ) : (
            <Button
              onClick={handleSetupPayoutAccount}
              disabled={isActionLoading}
            >
              Setup Payout Account
            </Button>
          )}
        </div>
      ) : (
        <OrgPayoutRequestControls
          earnings={earnings}
          isActionLoading={isActionLoading}
          isOwner={isOwner}
          isPaystackRail={isPaystackRail}
          onManageAccount={handleSetupPayoutAccount}
          onRequestPayout={handleRequestPayout}
        />
      )}
    </div>
  );
}
