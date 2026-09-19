"use client";

/**
 * Connected payout account for an attestor organization.
 *
 * Registering an org payout destination used to be write-only: nothing showed
 * an owner which bank account their earnings were addressed to, so a mistyped
 * account number was invisible and permanent. This names the account and, for
 * an owner, replaces it.
 *
 * Replacement registers the new account and retires the old one in one call
 * rather than offering removal on its own. An approved attestor application
 * points at a specific payout account, so retiring it alone would leave the
 * organization approved but with nowhere to be paid.
 *
 * Maps to: FR-FIN-* (organization payouts).
 */

import { useCallback, useEffect, useState } from "react";

import {
  listOrgPayoutAccounts,
  replaceOrgPayoutAccount,
} from "@/lib/generated/sdk.gen";
import type { PayoutAccountResponse } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import {
  PaystackBankFields,
  paystackDetailsComplete,
} from "@/components/modules/financials/paystack-bank-fields";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

interface OrgPayoutAccountCardProps {
  /** Organization whose payout destination is shown. */
  orgId: string;
  /** Whether the viewer owns the org; only an owner may replace the account. */
  isOwner: boolean;
  /** Reload the surrounding financials once the account changes. */
  onChange: () => void;
}

/**
 * Render the org's connected payout account and its replacement control.
 *
 * @param props - Org, viewer role, and the refresh hook.
 */
export function OrgPayoutAccountCard({
  orgId,
  isOwner,
  onChange,
}: OrgPayoutAccountCardProps) {
  const [accounts, setAccounts] = useState<PayoutAccountResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [bankCode, setBankCode] = useState("");
  const [accountNumber, setAccountNumber] = useState("");

  const load = useCallback(async () => {
    configureBrowserClient();
    const result = await listOrgPayoutAccounts({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId },
    });
    if (result.error || !result.data) {
      setError(describeGeneratedError(result.error));
      setLoading(false);
      return;
    }
    setAccounts(result.data.payout_accounts);
    setLoading(false);
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  const account = accounts[0];

  const handleReplace = useCallback(async () => {
    if (!account) return;
    setSubmitting(true);
    setError(null);
    configureBrowserClient();
    const result = await replaceOrgPayoutAccount({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, payout_account_id: account.id },
      body: {
        account_number: accountNumber,
        bank_code: bankCode,
        provider: "paystack" as const,
      },
    });
    setSubmitting(false);
    if (result.error || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setReplacing(false);
    setAccountNumber("");
    setBankCode("");
    await load();
    onChange();
  }, [account, accountNumber, bankCode, load, onChange, orgId]);

  if (loading) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-sm text-foreground-muted">Loading payout account.</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <h3 className="font-heading text-xl font-bold text-foreground">
        Connected account
      </h3>
      {error ? (
        <p className="mt-4 text-sm text-error" role="alert">
          {error}
        </p>
      ) : null}

      {!account ? (
        <p className="mt-4 text-sm text-foreground-muted">
          No payout account is connected yet.
        </p>
      ) : (
        <div className="mt-5 rounded-xl border border-border-default bg-surface-2 p-5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="font-heading text-base font-bold text-foreground">
                {account.provider === "paystack" ? "Bank account" : "Stripe"}
              </p>
              <p className="mt-1 text-sm text-foreground-muted">
                {account.provider_account_ref}
              </p>
              <p className="mt-2 text-xs text-foreground-muted">
                Attestation earnings are paid into this account.
              </p>
            </div>
            <span className="shrink-0 rounded-badge border border-border-default bg-surface-1 px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              {account.verified_at ? "Verified" : "Pending"}
            </span>
          </div>
        </div>
      )}

      {/* Stripe holds its own bank details, so a Connect account is changed
          at Stripe rather than replaced here — matching the API's refusal. */}
      {account && isOwner && account.provider === "paystack" ? (
        replacing ? (
          <div className="mt-5 grid gap-4 sm:max-w-md">
            <p className="text-sm text-foreground-muted">
              Enter the account that should receive earnings from now on. The
              current account is retired as soon as the new one is confirmed
              with the bank, so your organization is never left without one.
            </p>
            <PaystackBankFields
              accountNumber={accountNumber}
              bankCode={bankCode}
              disabled={submitting}
              idPrefix="org-replace-payout"
              onAccountNumberChange={setAccountNumber}
              onBankCodeChange={setBankCode}
            />
            <div className="flex flex-wrap gap-3">
              <Button
                type="button"
                onClick={handleReplace}
                disabled={
                  submitting || !paystackDetailsComplete(bankCode, accountNumber)
                }
                loading={submitting}
              >
                Replace bank account
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setReplacing(false)}
                disabled={submitting}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <Button
            className="mt-5"
            type="button"
            variant="secondary"
            onClick={() => setReplacing(true)}
          >
            Replace this account
          </Button>
        )
      ) : null}
    </div>
  );
}
