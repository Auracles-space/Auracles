"use client";

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
import { Spinner } from "@/components/ui/spinner";
import { TotpInput } from "@/components/modules/auth/totp-input";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

interface OrgAttestorFinancialsTabProps {
  orgId: string;
}

export function OrgAttestorFinancialsTab({ orgId }: OrgAttestorFinancialsTabProps) {
  const [earnings, setEarnings] = useState<EarningsResponse | null>(null);
  const [application, setApplication] = useState<OrgAttestorApplicationResponse | null>(null);
  const [invoices, setInvoices] = useState<OrgInvoiceListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [showTotp, setShowTotp] = useState(false);
  const [totpCode, setTotpCode] = useState("");
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
      setEarnings(earningsRes.data || null);
      setApplication(appRes.data || null);
      setInvoices(invoicesRes.data?.invoices || []);
    } catch (error) {
      console.error("Failed to fetch financials data:", error);
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
        body: {
          provider: "stripe",
          refresh_url: window.location.href,
          return_url: window.location.href,
        },
      });
      if (res.data?.onboarding_url) {
        window.location.href = res.data.onboarding_url;
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
    try {
      configureBrowserClient();
      await requestOrgPayout({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
        body: {
          amount: earnings.available_balance,
          currency: earnings.currency,
          payout_account_id: application.payout_account_id,
          totp_code: totpCode,
        },
      });
      setShowTotp(false);
      setTotpCode("");
      await fetchData(); // Refresh data
    } catch (error) {
      console.error("Failed to request payout:", error);
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

  return (
    <div className="space-y-8">
      {earnings && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
            <p className="text-sm text-foreground-subtle mb-1">Available Balance</p>
            <p className="text-2xl font-bold">
              {earnings.currency} {earnings.available_balance}
            </p>
          </div>
          <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
            <p className="text-sm text-foreground-subtle mb-1">Pending Clearance</p>
            <p className="text-2xl font-bold">
              {earnings.currency} {earnings.pending_clearance}
            </p>
          </div>
          <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
            <p className="text-sm text-foreground-subtle mb-1">Gross Revenue</p>
            <p className="text-2xl font-bold">
              {earnings.currency} {earnings.gross_revenue}
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
          <div className="text-sm text-foreground-subtle">
            <p className="font-medium text-warning">Account Pending</p>
            <p>Your application must be approved before you can setup payouts.</p>
          </div>
        ) : !application.payout_account_id ? (
          <div>
            <p className="text-sm text-foreground-subtle mb-4">
              You need to configure a payout account to receive earnings.
            </p>
            <Button onClick={handleSetupPayoutAccount} disabled={isActionLoading}>
              Setup Payout Account
            </Button>
          </div>
        ) : showTotp ? (
          <div className="max-w-sm space-y-4">
            <p className="text-sm text-foreground-subtle">
              Enter your authenticator code to confirm payout of {earnings?.currency} {earnings?.available_balance}
            </p>
            <TotpInput value={totpCode} onChange={setTotpCode} />
            <div className="flex gap-2">
              <Button 
                onClick={handleRequestPayout} 
                disabled={totpCode.length !== 6 || isActionLoading || parseFloat(earnings?.available_balance || "0") <= 0}
              >
                Confirm Payout
              </Button>
              <Button variant="secondary" onClick={() => setShowTotp(false)} disabled={isActionLoading}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div>
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => setShowTotp(true)}
                disabled={parseFloat(earnings?.available_balance || "0") <= 0}
              >
                Request Payout
              </Button>
              <Button
                variant="secondary"
                onClick={handleSetupPayoutAccount}
                disabled={isActionLoading}
              >
                Manage payout account
              </Button>
            </div>
            {parseFloat(earnings?.available_balance || "0") <= 0 && (
              <p className="text-sm text-foreground-subtle mt-2">
                No available balance to payout.
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
              <div key={invoice.id} className="p-4 rounded-lg bg-surface-2 border border-border-strong flex justify-between items-center">
                <div>
                  <p className="font-medium">{invoice.invoice_number}</p>
                  <p className="text-sm text-foreground-subtle">
                    {new Date(invoice.issue_date).toLocaleDateString()}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-bold">
                    {invoice.currency} {invoice.total}
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
