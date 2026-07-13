"use client";

/**
 * Contributor payout account connection.
 *
 * Uses Stripe Connect hosted onboarding. Auracles does not collect bank details
 * or account numbers; it stores and displays provider-hosted metadata only.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listPayoutAccounts,
  onboardPayoutAccount,
} from "@/lib/generated/sdk.gen";
import type { PayoutAccountResponse } from "@/lib/generated/types.gen";
import { Select } from "@/components/ui/select";
import { STRIPE_CONNECT_COUNTRIES } from "@/lib/marketplace/countries";
import { formatLabel } from "@/lib/marketplace/format";

/**
 * Render Stripe Connect onboarding and current payout account metadata.
 */
export function PayoutAccountConnect() {
  const [accounts, setAccounts] = useState<PayoutAccountResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  // Country the payout account is registered in. Determines which Stripe
  // onboarding form the contributor gets; defaults to the US.
  const [country, setCountry] = useState("US");

  useEffect(() => {
    async function loadAccounts() {
      configureBrowserClient();
      const result = await listPayoutAccounts({
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setAccounts(result.data.payout_accounts);
      setLoading(false);
    }

    void loadAccounts();
  }, []);

  async function handleConnect() {
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const origin = window.location.origin;
    const result = await onboardPayoutAccount({
      body: {
        country,
        provider: "stripe",
        refresh_url: `${origin}/settings/payout-accounts?refresh=1`,
        return_url: `${origin}/settings/payout-accounts?connected=1`,
      },
      headers: getAccessTokenHeaders(),
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    if (result.data.onboarding_url) {
      window.location.assign(result.data.onboarding_url);
      return;
    }

    setAccounts((current) => [result.data.payout_account, ...current]);
  }

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading payout accounts.</p>;
  }

  return (
    <section className="grid gap-6">
      <div className="flex items-center">
        <Link
          className="inline-flex items-center gap-2 text-sm font-semibold text-accent hover:underline"
          href="/dashboard/financials"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10 19l-7-7m0 0l7-7m-7 7h18"
            />
          </svg>
          Back to financials
        </Link>
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Stripe Connect
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Payout accounts
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-foreground-muted">
          Connect a provider-hosted payout account before requesting transfers.
          Bank details stay inside Stripe Connect.
        </p>
        {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}
        <div className="mt-5 max-w-xs">
          <label
            htmlFor="payout-country"
            className="mb-1 block text-sm font-semibold text-foreground"
          >
            Country
          </label>
          <Select
            id="payout-country"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
          >
            {STRIPE_CONNECT_COUNTRIES.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </Select>
          <p className="mt-1 text-xs text-foreground-muted">
            Where your payout account is registered. Stripe tailors onboarding
            to this country.
          </p>
        </div>
        <button
          className="mt-5 inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting}
          onClick={handleConnect}
          type="button"
        >
          {submitting ? "Opening Stripe" : "Connect Stripe"}
        </button>
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Connected accounts
        </h2>
        <div className="mt-5 grid gap-3">
          {accounts.length === 0 ? (
            <p className="text-sm text-foreground-muted">
              No payout account is connected yet.
            </p>
          ) : (
            accounts.map((account) => (
              <article
                className="rounded-xl border border-border-default bg-surface-2 p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
                key={account.id}
              >
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 className="font-heading text-base font-bold text-foreground">
                      Stripe {formatLabel(account.account_type)}
                    </h3>
                    <p className="mt-1 text-sm text-foreground-muted">
                      {account.provider_account_ref}
                    </p>
                  </div>
                  <span className="rounded-md border border-border-default bg-surface-1 px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                    {account.verified_at ? "Verified" : "Pending"}
                  </span>
                </div>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
