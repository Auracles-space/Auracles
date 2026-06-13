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
  PartnerPayoutResponse,
  PayoutAccountResponse,
} from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type PayoutPanelProps = {
  onRequest: (
    amount: string,
    payoutAccountId: string,
    totpCode: string,
  ) => Promise<void>;
  payouts: PartnerPayoutResponse[];
  verifiedAccounts: PayoutAccountResponse[];
};

/**
 * Render Partner payout request form and payout history.
 *
 * @param props - Verified payout accounts, existing payouts, and request callback.
 */
export function PayoutPanel({
  onRequest,
  payouts,
  verifiedAccounts,
}: PayoutPanelProps) {
  const amountId = useId();
  const accountId = useId();
  const totpId = useId();
  const [amount, setAmount] = useState("");
  const [payoutAccountId, setPayoutAccountId] = useState(
    verifiedAccounts[0]?.id ?? "",
  );
  const [totpCode, setTotpCode] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onRequest(amount, payoutAccountId, totpCode);
    setAmount("");
    setTotpCode("");
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Payouts
      </p>
      <h2 className="mt-1 font-heading text-xl font-bold">Partner payouts</h2>
      {verifiedAccounts.length > 0 ? (
        <form className="mt-5 grid gap-3" onSubmit={handleSubmit}>
          <label className="grid gap-2 text-sm font-semibold" htmlFor={amountId}>
            Amount
            <input
              className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
              id={amountId}
              inputMode="decimal"
              onChange={(event) => setAmount(event.target.value)}
              required
              value={amount}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold" htmlFor={accountId}>
            Payout account
            <select
              className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
              id={accountId}
              onChange={(event) => setPayoutAccountId(event.target.value)}
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
              className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
              id={totpId}
              inputMode="numeric"
              maxLength={6}
              onChange={(event) => setTotpCode(event.target.value)}
              pattern="[0-9]{6}"
              required
              value={totpCode}
            />
          </label>
          <button
            className="min-h-12 rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 px-4 text-sm font-semibold text-background"
            type="submit"
          >
            Request payout
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
