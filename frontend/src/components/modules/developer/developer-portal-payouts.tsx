"use client";

/**
 * Developer portal payout panel.
 *
 * Renders Partner payout request controls and payout history for approved
 * Developer partners with verified payout accounts.
 */
import type { FormEvent } from "react";
import { useId, useState } from "react";

import type {
  DeveloperSalesAnalyticsResponse,
  PartnerPayoutResponse,
  PayoutAccountResponse,
} from "@/lib/generated/types.gen";
import {
  allValid,
  isLengthBetween,
  isNonEmpty,
  isPositiveNumber,
} from "@/lib/forms/validators";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type PayoutPanelProps = {
  onRequest: (
    amount: string,
    payoutAccountId: string,
    totpCode: string,
  ) => Promise<void>;
  payouts: PartnerPayoutResponse[];
  verifiedAccounts: PayoutAccountResponse[];
  sales?: DeveloperSalesAnalyticsResponse | null;
  twoFactorEnabled: boolean;
};

/**
 * Render Partner payout request form and payout history.
 *
 * @param props - Verified payout accounts, existing payouts, sales metrics, and request callback.
 */
export function PayoutPanel({
  onRequest,
  payouts,
  verifiedAccounts,
  sales,
  twoFactorEnabled,
}: PayoutPanelProps) {
  const amountId = useId();
  const accountId = useId();
  const totpId = useId();
  const [amount, setAmount] = useState("");
  const [payoutAccountId, setPayoutAccountId] = useState(
    verifiedAccounts[0]?.id ?? "",
  );
  const [totpCode, setTotpCode] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [amountError, setAmountError] = useState<string | null>(null);
  const [totpError, setTotpError] = useState<string | null>(null);

  const parsedAmount = Number(amount);
  const clearedLimit = sales ? Number(sales.cleared_commission_amount) : Infinity;

  const canSubmit = allValid(
    isPositiveNumber(amount),
    parsedAmount <= clearedLimit,
    isNonEmpty(payoutAccountId),
    isLengthBetween(totpCode, 6, 6),
  ) && !isSubmitting;

  const handleAmountChange = (value: string) => {
    setAmount(value);
    const num = Number(value);
    const limit = sales ? Number(sales.cleared_commission_amount) : Infinity;

    if (value.trim() === "") {
      setAmountError(null);
    } else if (!isPositiveNumber(value)) {
      setAmountError("Please enter a positive amount");
    } else if (num > limit) {
      setAmountError(`Amount exceeds cleared balance of ${formatMoney(sales!.cleared_commission_amount)}`);
    } else {
      setAmountError(null);
    }
  };

  const handleTotpChange = (value: string) => {
    setTotpCode(value);
    if (value.trim() === "" || isLengthBetween(value, 6, 6)) {
      setTotpError(null);
    } else {
      setTotpError("Code must be exactly 6 characters");
    }
  };

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isPositiveNumber(amount)) {
      setAmountError("Please enter a positive amount");
      return;
    }
    const limit = sales ? Number(sales.cleared_commission_amount) : Infinity;
    if (Number(amount) > limit) {
      setAmountError(`Amount exceeds cleared balance of ${formatMoney(sales!.cleared_commission_amount)}`);
      return;
    }
    if (!isLengthBetween(totpCode, 6, 6)) {
      setTotpError("Code must be exactly 6 characters");
      return;
    }
    setIsSubmitting(true);
    try {
      await onRequest(amount, payoutAccountId, totpCode);
      setAmount("");
      setTotpCode("");
      setAmountError(null);
      setTotpError(null);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Payouts
      </p>
      <h2 className="mt-1 font-heading text-xl font-bold">Partner payouts</h2>

      {sales && (
        <div className="mt-4 grid grid-cols-1 min-[400px]:grid-cols-3 gap-3 rounded-xl border border-border-default bg-surface-2 p-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              Cleared Balance
            </p>
            <p className="mt-0.5 text-base font-bold text-success">
              {formatMoney(sales.cleared_commission_amount)}
            </p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              Pending Clear
            </p>
            <p className="mt-0.5 text-base font-bold text-warning">
              {formatMoney(sales.pending_commission_amount)}
            </p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              Paid Out
            </p>
            <p className="mt-0.5 text-base font-bold text-foreground">
              {formatMoney(sales.paid_commission_amount)}
            </p>
          </div>
        </div>
      )}

      {!twoFactorEnabled ? (
        <div className="mt-5 rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
          Payouts require two-factor authentication.{" "}
          <a className="font-semibold underline" href="/2fa-setup">
            Set up 2FA
          </a>{" "}
          to request a payout.
        </div>
      ) : verifiedAccounts.length > 0 ? (
        <form className="mt-5 grid gap-3" onSubmit={handleSubmit}>
          <label className="grid gap-2 text-sm font-semibold" htmlFor={amountId}>
            <div className="flex items-center justify-between">
              <span>Amount</span>
              {sales && Number(sales.cleared_commission_amount) > 0 && (
                <button
                  type="button"
                  onClick={() => handleAmountChange(sales.cleared_commission_amount)}
                  className="text-xs font-semibold text-accent hover:underline outline-none focus-visible:ring-1 focus-visible:ring-accent rounded px-1"
                >
                  Use Max Available ({formatMoney(sales.cleared_commission_amount)})
                </button>
              )}
            </div>
            <input
              className={`min-h-12 rounded-xl border bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 ${
                amountError ? "border-error focus-visible:ring-error" : "border-border-default"
              }`}
              id={amountId}
              inputMode="decimal"
              onChange={(event) => handleAmountChange(event.target.value)}
              required
              disabled={isSubmitting}
              value={amount}
              placeholder="e.g. 100.00"
            />
            {amountError ? (
              <span className="text-xs text-error font-normal">{amountError}</span>
            ) : null}
          </label>
          <label className="grid gap-2 text-sm font-semibold" htmlFor={accountId}>
            Payout account
            <select
              className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
              id={accountId}
              onChange={(event) => setPayoutAccountId(event.target.value)}
              disabled={isSubmitting}
              value={payoutAccountId}
            >
              {verifiedAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.provider} {account.provider_account_ref}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-semibold" htmlFor={totpId}>
            Authenticator code
            <input
              className={`min-h-12 rounded-xl border bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 ${
                totpError ? "border-error focus-visible:ring-error" : "border-border-default"
              }`}
              id={totpId}
              inputMode="numeric"
              maxLength={6}
              onChange={(event) => handleTotpChange(event.target.value)}
              pattern="[0-9]{6}"
              required
              disabled={isSubmitting}
              value={totpCode}
              placeholder="000000"
            />
            {totpError ? (
              <span className="text-xs text-error font-normal">{totpError}</span>
            ) : null}
          </label>
          <button
            className="min-h-12 rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 px-4 text-sm font-semibold text-background disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!canSubmit}
            type="submit"
          >
            {isSubmitting ? "Requesting payout..." : "Request payout"}
          </button>
        </form>
      ) : (
        <p className="mt-4 text-sm text-foreground-muted">
          Connect and verify a payout account before requesting Partner payouts.
        </p>
      )}
      <div className="mt-5 grid gap-2">
        {payouts.map((payout) => (
          <div
            className="rounded-xl border border-border-default bg-surface-2 p-3"
            key={payout.id}
          >
            <p className="text-sm font-semibold">{payout.id}</p>
            <p className="mt-1 text-sm text-foreground-muted">
              {formatMoney(payout.amount, payout.currency)} ·{" "}
              {formatLabel(payout.status)}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
