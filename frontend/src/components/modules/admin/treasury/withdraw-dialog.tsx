"use client";

/**
 * Platform withdrawal dialog (super-admin only).
 *
 * Checks the amount against what Treasury says is withdrawable before sending,
 * but the API remains the authority: the minimum, the one-in-flight rule and
 * the bank account hold are enforced there and their messages shown here.
 * The request needs a step-up window, which the global step-up prompt opens
 * when the API asks for one.
 *
 * Maps to: platform treasury design, decisions 2, 4 and 10.
 */
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { adminRequestPlatformWithdrawalV1AdminTreasuryWithdrawalsPost as requestWithdrawal } from "@/lib/generated/sdk.gen";
import type { PlatformBankAccountItem } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

/**
 * Normalise typed money input to a plain decimal with at most two places.
 *
 * @param raw - What the admin typed.
 */
function cleanAmount(raw: string): string {
  const digits = raw.replace(/[^\d.]/g, "");
  const [whole, ...rest] = digits.split(".");
  return rest.length ? `${whole}.${rest.join("").slice(0, 2)}` : whole;
}

/**
 * Render the withdrawal dialog.
 *
 * @param open - Whether the dialog is shown.
 * @param withdrawable - Treasury's withdrawable amount, as a decimal string.
 * @param currency - Currency of the withdrawal (NGN).
 * @param bankAccount - Destination account, shown by last four digits.
 * @param onClose - Called when dismissed.
 * @param onRequested - Called after the API accepted the withdrawal.
 */
export function WithdrawDialog({
  open,
  withdrawable,
  currency,
  bankAccount,
  onClose,
  onRequested,
}: {
  open: boolean;
  withdrawable: string;
  currency: string;
  bankAccount: PlatformBankAccountItem | null;
  onClose: () => void;
  onRequested: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const value = Number(amount);
  const tooMuch = amount !== "" && value > Number(withdrawable);
  const invalid = amount === "" || !(value > 0) || tooMuch;

  function close() {
    setAmount("");
    setError(null);
    onClose();
  }

  async function submit() {
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await requestWithdrawal({
      headers: getAccessTokenHeaders(),
      body: { amount },
    });
    setBusy(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setAmount("");
    onRequested();
  }

  return (
    <ConfirmDialog
      busy={busy}
      confirmDisabled={invalid}
      confirmLabel={`Withdraw ${formatMoney(amount || "0", currency)}`}
      description={
        <div className="grid gap-3">
          <p>
            Sends platform money to{" "}
            {bankAccount
              ? `${bankAccount.bank_name} ****${bankAccount.account_last4}`
              : "the platform bank account"}
            . Every admin is notified.
          </p>
          <div>
            <label
              className="mb-1 block text-sm font-semibold text-foreground"
              htmlFor="treasury-withdraw-amount"
            >
              Amount ({currency})
            </label>
            <input
              className="flex min-h-12 w-full rounded-xl border border-border-default bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
              id="treasury-withdraw-amount"
              inputMode="decimal"
              onChange={(event) => setAmount(cleanAmount(event.target.value))}
              placeholder="10000"
              value={amount}
            />
            <p className={["mt-1 text-xs", tooMuch ? "text-error" : "text-foreground-muted"].join(" ")}>
              {tooMuch
                ? `That is more than is available (${formatMoney(withdrawable, currency)}).`
                : `Up to ${formatMoney(withdrawable, currency)} is available.`}
            </p>
          </div>
        </div>
      }
      error={error}
      eyebrow="Platform withdrawal"
      onClose={close}
      onConfirm={() => void submit()}
      open={open}
      title="Withdraw platform money"
    />
  );
}
