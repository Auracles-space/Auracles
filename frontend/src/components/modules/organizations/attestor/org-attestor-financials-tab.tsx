"use client";

/**
 * Attestor organization financials tab.
 *
 * Shows the org's attestation earnings, lets an org admin link a payout
 * account (Paystack bank details on the NGN rail, Stripe Connect elsewhere),
 * request a payout of the available balance, and browse invoices. Requesting a
 * payout is a sensitive action: the API requires a step-up 2FA window, which
 * the global step-up prompt handles when the call is refused.
 *
 * Every amount is formatted in the currency the earnings or invoice response
 * carries (naira on the NGN rail), never an assumed default.
 *
 * Maps to: FR-FIN-* (organization payouts).
 */
import { useEffect, useState } from "react";
import {
  getOrgAttestorEarnings,
  onboardOrgPayoutAccount,
  requestOrgPayout,
  listOrgInvoices,
  getOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type { EarningsResponse, OrgAttestorApplicationResponse, OrgInvoiceListItem } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import {
  PaystackBankFields,
  paystackDetailsComplete,
} from "@/components/modules/financials/paystack-bank-fields";
import { payoutProviderForCountry } from "@/lib/marketplace/currency";
import { formatMoney } from "@/lib/marketplace/format";
import { Spinner } from "@/components/ui/spinner";
import { ownerStatusKey, StatusPill } from "@/components/ui/status-pill";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

interface OrgAttestorFinancialsTabProps {
  /** Organization whose earnings, payout account, and invoices are shown. */
  orgId: string;
}

/**
 * Render earnings, payout controls, and invoices for one attestor org.
 *
 * @param orgId - Organization whose financials are shown.
 */
export function OrgAttestorFinancialsTab({ orgId }: OrgAttestorFinancialsTabProps) {
  const [earnings, setEarnings] = useState<EarningsResponse | null>(null);
  const [application, setApplication] = useState<OrgAttestorApplicationResponse | null>(null);
  const [invoices, setInvoices] = useState<OrgInvoiceListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [bankCode, setBankCode] = useState("");
  const [accountNumber, setAccountNumber] = useState("");

  // Mirrors the backend routing. On an NGN deployment Stripe Connect cannot pay
  // out at all, so bank details are collected here instead of redirecting.
  const isPaystackRail = payoutProviderForCountry("") === "paystack";
  const [payoutError, setPayoutError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      const [earningsRes, appRes, invoicesRes] = await Promise.all([
        getOrgAttestorEarnings({ headers, path: { org_id: orgId } }),
        getOrgAttestorApplication({ headers, path: { org_id: orgId } }),
        listOrgInvoices({ headers, path: { org_id: orgId } }),
      ]);
      // The generated client resolves non-2xx responses with `error` rather
      // than throwing. An org with no attestor application (a contributor-only
      // org) legitimately 404s there, so only other failures are surfaced.
      const appMissing = appRes.response?.status === 404;
      const failure =
        earningsRes.error ??
        (appMissing ? undefined : appRes.error) ??
        invoicesRes.error;
      setLoadError(failure ? describeGeneratedError(failure) : null);
      setEarnings(earningsRes.data || null);
      setApplication(appRes.data || null);
      setInvoices(invoicesRes.data?.invoices || []);
    } catch (error) {
      setLoadError(describeGeneratedError(error));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  const handleSetupPayoutAccount = async () => {
    setIsActionLoading(true);
    setPayoutError(null);
    try {
      configureBrowserClient();
      const res = await onboardOrgPayoutAccount({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
        body: isPaystackRail
          ? {
              account_number: accountNumber,
              bank_code: bankCode,
              provider: "paystack" as const,
            }
          : {
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
        // Paystack registers the account outright — there is no redirect, so
        // refresh in place to pick up the now-linked payout account.
        await fetchData();
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
      await fetchData(); // Refresh data
    } catch (error) {
      console.error("Failed to request payout:", error);
      setPayoutError("The request could not be completed.");
    } finally {
      setIsActionLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  const availableAmount = Number(earnings?.available_balance ?? "0");
  const minimumAmount = Number(earnings?.minimum_payout ?? "0");
  const hasNoBalance = !(availableAmount > 0);
  // Same threshold the API enforces; checked here so the org learns why the
  // button is off instead of meeting a refusal after a step-up prompt.
  const belowMinimum = !hasNoBalance && availableAmount < minimumAmount;

  return (
    <div className="space-y-8">
      {loadError && (
        <p
          className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error"
          role="alert"
        >
          {loadError}
        </p>
      )}
      {earnings && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
            <p className="text-sm text-foreground-subtle mb-1">Available Balance</p>
            <p className="text-2xl font-bold">
              {formatMoney(earnings.available_balance, earnings.currency)}
            </p>
            <p className="mt-1 text-xs text-foreground-subtle">
              Minimum payout {formatMoney(earnings.minimum_payout, earnings.currency)}
            </p>
          </div>
          <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
            <p className="text-sm text-foreground-subtle mb-1">Pending Clearance</p>
            <p className="text-2xl font-bold">
              {formatMoney(earnings.pending_clearance, earnings.currency)}
            </p>
          </div>
          <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
            <p className="text-sm text-foreground-subtle mb-1">Gross Revenue</p>
            <p className="text-2xl font-bold">
              {formatMoney(earnings.gross_revenue, earnings.currency)}
            </p>
          </div>
        </div>
      )}

      <div className="p-6 rounded-lg bg-surface-2 border border-border-strong">
        <h3 className="text-lg font-medium mb-4">Payout Actions</h3>
        {payoutError && (
          <p className="text-sm text-error mb-4" role="alert">
            {payoutError}
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
              <div className="mb-4">
                <PaystackBankFields
                  accountNumber={accountNumber}
                  bankCode={bankCode}
                  disabled={isActionLoading}
                  idPrefix="org-financials-payout"
                  onAccountNumberChange={setAccountNumber}
                  onBankCodeChange={setBankCode}
                />
              </div>
            ) : null}
            <Button
              onClick={handleSetupPayoutAccount}
              disabled={
                isActionLoading ||
                (isPaystackRail &&
                  !paystackDetailsComplete(bankCode, accountNumber))
              }
            >
              Setup Payout Account
            </Button>
          </div>
        ) : (
          <div>
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={handleRequestPayout}
                disabled={isActionLoading || hasNoBalance || belowMinimum}
              >
                Request Payout
              </Button>
              <Button
                className={isPaystackRail ? "hidden" : undefined}
                variant="secondary"
                onClick={handleSetupPayoutAccount}
                disabled={isActionLoading}
              >
                Manage payout account
              </Button>
            </div>
            {hasNoBalance && (
              <p className="text-sm text-foreground-subtle mt-2">
                No available balance to payout.
              </p>
            )}
            {belowMinimum && earnings && (
              <p className="text-sm text-foreground-subtle mt-2">
                Your available balance is below the minimum payout of{" "}
                {formatMoney(earnings.minimum_payout, earnings.currency)}.
              </p>
            )}
          </div>
        )}
      </div>

      <div>
        <h3 className="text-lg font-medium mb-4">Invoices</h3>
        {invoices.length === 0 ? (
          <p className="text-sm text-foreground-subtle">No invoices found.</p>
        ) : (
          <div className="space-y-4">
            {invoices.map((invoice) => (
              <div
                key={invoice.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-strong bg-surface-2 p-4"
              >
                <div className="min-w-0">
                  <p className="break-all font-medium">{invoice.invoice_number}</p>
                  <p className="text-sm text-foreground-subtle">
                    {new Date(invoice.issue_date).toLocaleDateString()}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-bold">
                    {formatMoney(invoice.total, invoice.currency.toUpperCase())}
                  </p>
                  <p className="text-xs text-foreground-subtle uppercase">{invoice.doc_type}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
