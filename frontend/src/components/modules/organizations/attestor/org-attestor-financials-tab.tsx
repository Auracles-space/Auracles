"use client";

/**
 * Attestor organization financials tab.
 *
 * Shows the org's attestation earnings, lets an org admin link a payout
 * account (Paystack bank details on the NGN rail, Stripe Connect elsewhere),
 * request a payout of the available balance, and browse payouts and invoices.
 * The earnings response carries a payout eligibility checklist; while any
 * condition is unmet the checklist explains it and the request stays disabled.
 * Only the organization owner may request a payout (spec 2026-09-14,
 * Decision 3). Requesting a payout is a sensitive action: the API requires a
 * step-up 2FA window, which the global step-up prompt handles when refused.
 *
 * Every amount is formatted in the currency the earnings or invoice response
 * carries (naira on the NGN rail), never an assumed default.
 *
 * This file owns loading; the earnings cards, payout actions, and request
 * controls live in sibling `org-earnings-summary`, `org-payout-actions`, and
 * `org-payout-request-controls` files.
 *
 * Maps to: FR-FIN-* (organization payouts).
 */
import { useEffect, useState } from "react";
import {
  getOrgAttestorEarnings,
  listOrgInvoices,
  getOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type {
  OrgAttestorApplicationResponse,
  OrgEarningsResponse,
  OrgInvoiceListItem,
} from "@/lib/generated/types.gen";
import { Spinner } from "@/components/ui/spinner";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { useOrganization } from "@/components/modules/organizations/organization-context";

import { OrgEarningsSummary } from "./org-earnings-summary";
import { OrgInvoiceList } from "./org-invoice-list";
import { OrgPayoutAccountCard } from "./org-payout-account-card";
import { OrgPayoutActions } from "./org-payout-actions";
import { OrgPayoutHistory } from "./org-payout-history";

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
  const { role } = useOrganization();
  const isOwner = role === "owner";
  const [earnings, setEarnings] = useState<OrgEarningsResponse | null>(null);
  const [application, setApplication] = useState<OrgAttestorApplicationResponse | null>(null);
  const [invoices, setInvoices] = useState<OrgInvoiceListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

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

  if (isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

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
      {earnings && <OrgEarningsSummary earnings={earnings} />}

      <OrgPayoutActions
        application={application}
        earnings={earnings}
        isOwner={isOwner}
        onRefresh={fetchData}
        orgId={orgId}
      />

      <OrgPayoutAccountCard
        isOwner={isOwner}
        onChange={fetchData}
        orgId={orgId}
      />

      <OrgPayoutHistory orgId={orgId} />

      <OrgInvoiceList invoices={invoices} />
    </div>
  );
}
