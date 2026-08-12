"use client";

/**
 * Contributor payout account connection.
 *
 * Two rails, chosen by the account's country. Stripe Connect runs hosted
 * onboarding, so Auracles never sees a bank detail — the contributor is
 * redirected and Stripe collects everything. Paystack has no hosted flow, so
 * the NUBAN account number and bank code are collected here and registered as
 * a transfer recipient; Paystack resolving them against the bank is what
 * verifies the account, and the confirmed name is shown back so a mistyped
 * account number is caught before any money is addressed to it.
 *
 * Maps to: FR-FIN-* (Contributor payout onboarding).
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listPayoutAccounts,
  listPayoutBanks,
  onboardPayoutAccount,
} from "@/lib/generated/sdk.gen";
import type {
  PayoutAccountResponse,
  PayoutBank,
} from "@/lib/generated/types.gen";
import { Select } from "@/components/ui/select";
import { PAYOUT_COUNTRIES } from "@/lib/marketplace/countries";
import { payoutProviderForCountry } from "@/lib/marketplace/currency";
import { formatLabel } from "@/lib/marketplace/format";

/** NUBAN account numbers are always exactly ten digits. */
const NUBAN_LENGTH = 10;

/**
 * Render payout onboarding and current payout account metadata.
 */
export function PayoutAccountConnect() {
  const [accounts, setAccounts] = useState<PayoutAccountResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  // Country the payout account is registered in. Decides the rail, so it also
  // decides which fields below are asked for.
  const [country, setCountry] = useState("US");
  const [banks, setBanks] = useState<PayoutBank[]>([]);
  const [bankCode, setBankCode] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [confirmedName, setConfirmedName] = useState<string | null>(null);

  // Mirrors the backend's routing rather than checking the country alone: on
  // an NGN deployment every country settles through Paystack, so a
  // country-only rule would ask Stripe to pay an account it cannot.
  const isPaystackRail = payoutProviderForCountry(country) === "paystack";

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

  // Bank codes change and new institutions appear, so the list is read from
  // the provider on demand rather than shipped in the bundle.
  useEffect(() => {
    if (!isPaystackRail) {
      return;
    }
    async function loadBanks() {
      configureBrowserClient();
      const result = await listPayoutBanks({ headers: getAccessTokenHeaders() });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setBanks(result.data.banks);
    }

    void loadBanks();
  }, [isPaystackRail]);

  const handleConnect = useCallback(async () => {
    setError(null);
    setConfirmedName(null);
    setSubmitting(true);
    configureBrowserClient();
    const origin = window.location.origin;
    const body = isPaystackRail
      ? {
          account_number: accountNumber,
          bank_code: bankCode,
          country,
          provider: "paystack" as const,
        }
      : {
          country,
          provider: "stripe" as const,
          refresh_url: `${origin}/settings/payout-accounts?refresh=1`,
          return_url: `${origin}/settings/payout-accounts?connected=1`,
        };
    const result = await onboardPayoutAccount({
      body,
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

    // Paystack settles here: nothing to redirect to, so the new account and
    // the bank-confirmed name are rendered in place.
    setConfirmedName(result.data.account_name ?? null);
    setAccounts((current) => [result.data.payout_account, ...current]);
    setAccountNumber("");
  }, [accountNumber, bankCode, country, isPaystackRail]);

  const canSubmit = isPaystackRail
    ? bankCode !== "" && accountNumber.length === NUBAN_LENGTH
    : true;

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
          {isPaystackRail ? "Paystack" : "Stripe Connect"}
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Payout accounts
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-foreground-muted">
          {isPaystackRail
            ? "Add the bank account your earnings should be paid into. Payouts are sent straight to this account."
            : "Connect a provider-hosted payout account before requesting transfers. Bank details stay inside Stripe Connect."}
        </p>
        {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}
        {confirmedName ? (
          <p className="mt-4 rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground">
            Connected. Payouts will be sent to{" "}
            <strong className="font-semibold">{confirmedName}</strong>. If that
            is not your name, remove this account and check the number.
          </p>
        ) : null}

        <div className="mt-5 grid gap-4 sm:max-w-md">
          <div>
            <label
              htmlFor="payout-country"
              className="mb-1 block text-sm font-semibold text-foreground"
            >
              Country
            </label>
            <Select
              id="payout-country"
              value={country}
              onChange={(event) => setCountry(event.target.value)}
            >
              {PAYOUT_COUNTRIES.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.name}
                </option>
              ))}
            </Select>
            <p className="mt-1 text-xs text-foreground-muted">
              Where your payout account is registered. This decides how your
              earnings are sent.
            </p>
          </div>

          {isPaystackRail ? (
            <>
              <div>
                <label
                  htmlFor="payout-bank"
                  className="mb-1 block text-sm font-semibold text-foreground"
                >
                  Bank
                </label>
                <Select
                  id="payout-bank"
                  value={bankCode}
                  onChange={(event) => setBankCode(event.target.value)}
                >
                  <option value="">Select a bank</option>
                  {banks.map((bank) => (
                    <option key={bank.code} value={bank.code}>
                      {bank.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <label
                  htmlFor="payout-account-number"
                  className="mb-1 block text-sm font-semibold text-foreground"
                >
                  Account number
                </label>
                <input
                  className="flex min-h-12 w-full rounded-xl border border-border-default bg-surface-1 px-3 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
                  id="payout-account-number"
                  inputMode="numeric"
                  maxLength={NUBAN_LENGTH}
                  onChange={(event) =>
                    setAccountNumber(event.target.value.replace(/\D/g, ""))
                  }
                  pattern="\d{10}"
                  placeholder="0123456789"
                  value={accountNumber}
                />
                <p className="mt-1 text-xs text-foreground-muted">
                  Your {NUBAN_LENGTH}-digit NUBAN account number. We confirm the
                  account name with your bank before any payout is sent.
                </p>
              </div>
            </>
          ) : null}
        </div>

        <button
          className="mt-5 inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting || !canSubmit}
          onClick={handleConnect}
          type="button"
        >
          {isPaystackRail
            ? submitting
              ? "Connecting"
              : "Connect bank account"
            : submitting
              ? "Opening Stripe"
              : "Connect Stripe"}
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
                      {account.provider === "paystack" ? "Bank account" : "Stripe"}{" "}
                      {formatLabel(account.account_type)}
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
