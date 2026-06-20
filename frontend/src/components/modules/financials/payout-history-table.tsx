"use client";

/**
 * Contributor payout history and request controls.
 *
 * The browser collects only payout amount, selected provider account, and a
 * fresh authenticator code. Balance, KYC, 2FA, and minimum-payout enforcement
 * stay server-side in the financials API.
 */
import Link from "next/link";
import type { FormEvent } from "react";
import { useEffect, useId, useMemo, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  allValid,
  isLengthBetween,
  isNonEmpty,
  isPositiveNumber,
} from "@/lib/forms/validators";
import {
  listPayoutAccounts,
  listPayouts,
  requestPayout,
} from "@/lib/generated/sdk.gen";
import type {
  PayoutAccountResponse,
  PayoutResponse,
} from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

/**
 * Render Contributor payout rows and a TOTP-gated payout request modal.
 */
export function PayoutHistoryTable() {
  const [accounts, setAccounts] = useState<PayoutAccountResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [payouts, setPayouts] = useState<PayoutResponse[]>([]);

  useEffect(() => {
    async function loadPayoutWorkspace() {
      configureBrowserClient();
      const [accountResult, payoutResult] = await Promise.all([
        listPayoutAccounts({ headers: getAccessTokenHeaders() }),
        listPayouts({ headers: getAccessTokenHeaders() }),
      ]);

      if (!accountResult.response.ok || !accountResult.data) {
        setError(describeGeneratedError(accountResult.error));
        setLoading(false);
        return;
      }
      if (!payoutResult.response.ok || !payoutResult.data) {
        setError(describeGeneratedError(payoutResult.error));
        setLoading(false);
        return;
      }

      setAccounts(accountResult.data.payout_accounts);
      setPayouts(payoutResult.data.payouts);
      setLoading(false);
    }

    void loadPayoutWorkspace();
  }, []);

  function handlePayoutCreated(payout: PayoutResponse) {
    setPayouts((current) => [payout, ...current]);
  }

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading payouts.</p>;
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 shadow-sm">
      <div className="flex flex-col gap-4 border-b border-border-default p-4 md:flex-row md:items-center md:justify-between md:p-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Contributor payouts
          </p>
          <h2 className="mt-1 font-heading text-xl font-bold text-foreground">
            Payout history
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Request transfers to your verified Stripe Connect account.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground transition-all hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
            href="/settings/payout-accounts"
          >
            Manage payout accounts
          </Link>
          <button
            className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!accounts.some((account) => account.verified_at)}
            onClick={() => setModalOpen(true)}
            type="button"
          >
            Request payout
          </button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <p className="p-4 text-sm text-foreground-muted md:p-5">
          Connect a payout account before requesting transfers.{" "}
          <Link className="font-semibold text-accent" href="/settings/payout-accounts">
            Open payout settings
          </Link>
        </p>
      ) : null}

      {payouts.length === 0 ? (
        <p className="p-4 text-sm text-foreground-muted md:p-5">
          No payouts have been requested yet.
        </p>
      ) : (
        <div className="grid divide-y divide-border-default">
          {payouts.map((payout) => (
            <PayoutRow key={payout.id} payout={payout} />
          ))}
        </div>
      )}

      {modalOpen ? (
        <PayoutRequestModal
          accounts={accounts}
          onClose={() => setModalOpen(false)}
          onCreated={handlePayoutCreated}
        />
      ) : null}
    </section>
  );
}

type PayoutRowProps = {
  payout: PayoutResponse;
};

/**
 * Render one payout request row.
 *
 * @param props - Payout response returned by the generated financials client.
 */
function PayoutRow({ payout }: PayoutRowProps) {
  const completedLabel = payout.completed_at
    ? new Date(payout.completed_at).toLocaleDateString()
    : "Not completed";

  return (
    <article className="grid gap-4 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:p-5">
      <div>
        <h3 className="font-heading text-base font-bold text-foreground">
          {formatMoney(payout.net_amount, payout.currency)}
        </h3>
        <p className="mt-1 text-sm text-foreground-muted">
          Gross {formatMoney(payout.amount, payout.currency)} minus{" "}
          {formatMoney(payout.commission_deducted, payout.currency)} commission
        </p>
        <p className="mt-1 text-sm text-foreground-muted">
          {payout.provider_ref ?? "Pending transfer"}
        </p>
      </div>
      <div className="flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-[0.05em] md:justify-end">
        <span className="rounded-md border border-border-default bg-surface-2 px-2 py-1 text-foreground-muted">
          {formatLabel(payout.status)}
        </span>
        <span className="rounded-md border border-border-default bg-surface-2 px-2 py-1 text-foreground-muted">
          Requested {new Date(payout.initiated_at).toLocaleDateString()}
        </span>
        <span className="rounded-md border border-border-default bg-surface-2 px-2 py-1 text-foreground-muted">
          {completedLabel}
        </span>
      </div>
    </article>
  );
}

type PayoutRequestModalProps = {
  accounts: PayoutAccountResponse[];
  onClose: () => void;
  onCreated: (payout: PayoutResponse) => void;
};

/**
 * Collect payout amount and a fresh TOTP code before calling the payout API.
 *
 * @param props - Verified payout accounts and modal callbacks.
 */
export function PayoutRequestModal({
  accounts,
  onClose,
  onCreated,
}: PayoutRequestModalProps) {
  const amountId = useId();
  const accountId = useId();
  const totpId = useId();
  const verifiedAccounts = useMemo(
    () => accounts.filter((account) => account.verified_at),
    [accounts],
  );
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [payoutAccountId, setPayoutAccountId] = useState(
    verifiedAccounts[0]?.id ?? "",
  );
  const [submitting, setSubmitting] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const canSubmit = allValid(
    isPositiveNumber(amount),
    isNonEmpty(payoutAccountId),
    isLengthBetween(totpCode, 6, 6),
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await requestPayout({
      body: {
        amount,
        currency: "USD",
        payout_account_id: payoutAccountId,
        totp_code: totpCode,
      },
      headers: getAccessTokenHeaders(),
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    onCreated(result.data);
    onClose();
  }

  return (
    <div
      aria-labelledby="payout-request-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 sm:place-items-center sm:p-4"
      role="dialog"
      onClick={onClose}
    >
      <form
        className="w-full rounded-t-2xl border border-border-default bg-surface-1 p-5 shadow-xl sm:max-w-md sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
        onSubmit={handleSubmit}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Secure payout
            </p>
            <h2
              className="mt-1 font-heading text-xl font-bold text-foreground"
              id="payout-request-title"
            >
              Request payout
            </h2>
          </div>
          <button
            className="rounded-xl px-3 py-2 text-sm font-semibold text-foreground-muted outline-none transition-all hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
            onClick={onClose}
            type="button"
          >
            Close
          </button>
        </div>

        {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}

        <div className="mt-5 grid gap-4">
          <label className="grid gap-2 text-sm font-semibold text-foreground" htmlFor={amountId}>
            Amount
            <input
              className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 text-sm font-normal text-foreground outline-none transition-all focus:border-accent focus:ring-0"
              id={amountId}
              inputMode="decimal"
              onChange={(event) => setAmount(event.target.value)}
              placeholder="200.00"
              required
              type="text"
              value={amount}
            />
          </label>

          <label className="grid gap-2 text-sm font-semibold text-foreground" htmlFor={accountId}>
            Payout account
            <select
              className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 text-sm font-normal text-foreground outline-none transition-all focus:border-accent focus:ring-0"
              id={accountId}
              onChange={(event) => setPayoutAccountId(event.target.value)}
              required
              value={payoutAccountId}
            >
              {verifiedAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  Stripe {formatLabel(account.account_type)} {account.provider_account_ref}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-2 text-sm font-semibold text-foreground" htmlFor={totpId}>
            Authenticator code
            <input
              autoComplete="one-time-code"
              className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 text-sm font-normal text-foreground outline-none transition-all focus:border-accent focus:ring-0"
              id={totpId}
              inputMode="numeric"
              maxLength={6}
              onChange={(event) => setTotpCode(event.target.value)}
              pattern="[0-9]{6}"
              required
              type="text"
              value={totpCode}
            />
          </label>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-3">
          <button
            className="min-h-12 rounded-xl border border-border-default px-4 text-sm font-semibold text-foreground outline-none transition-all hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
            onClick={onClose}
            type="button"
          >
            Cancel
          </button>
          <button
            className="min-h-12 rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
            disabled={submitting || !canSubmit}
            type="submit"
          >
            {submitting ? "Submitting" : "Submit payout request"}
          </button>
        </div>
      </form>
    </div>
  );
}
