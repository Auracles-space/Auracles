"use client";

/**
 * Bank details with a confirmation step, for every Paystack payout surface.
 *
 * A mistyped NUBAN is rarely invalid — it almost always belongs to a real
 * stranger, so the bank accepts it and nothing downstream catches it. The only
 * moment the mistake is visible is before the account is registered, which is
 * why the account holder's name is fetched and shown back for acceptance
 * first. Nothing is registered until the person says the name is theirs.
 *
 * Shared by the personal payout settings page and the organization payout
 * surfaces so all three ask the same question and refuse in the same way. The
 * lookup itself registers nothing, so rejecting a name leaves no trace to
 * clean up.
 *
 * Maps to: FR-FIN-* (payout onboarding, Nigerian corridor).
 */

import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  PaystackBankFields,
  paystackDetailsComplete,
  type BankListLoader,
} from "@/components/modules/financials/paystack-bank-fields";

/** One Nigerian bank account, as entered. */
export interface BankDetails {
  accountNumber: string;
  bankCode: string;
}

/** The resolved holder name, or the reason the lookup failed. */
export type ResolveResult = { name: string } | { error: string };

export interface ConfirmBankAccountProps {
  /** Prefix for input ids, so two instances can coexist on one page. */
  idPrefix: string;
  /** Look up the name the bank holds, registering nothing. */
  resolve: (details: BankDetails) => Promise<ResolveResult>;
  /** Register the account once its holder has been accepted. */
  onConfirm: (details: BankDetails) => Promise<{ error: string } | null>;
  /** Label for the button that registers the confirmed account. */
  confirmLabel?: string;
  /** Bank list source, for surfaces whose role cannot use the default. */
  loadBanks?: BankListLoader;
}

/**
 * Render bank details, a name check, and the confirmation that registers them.
 *
 * @param props - Ids, the lookup and registration callbacks, and copy.
 */
export function ConfirmBankAccount({
  idPrefix,
  resolve,
  onConfirm,
  confirmLabel = "Yes, use this account",
  loadBanks,
}: ConfirmBankAccountProps) {
  const [bankCode, setBankCode] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [accountName, setAccountName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleCheck = useCallback(async () => {
    setBusy(true);
    setError(null);
    const result = await resolve({ accountNumber, bankCode });
    setBusy(false);
    if ("error" in result) {
      setError(result.error);
      return;
    }
    setAccountName(result.name);
  }, [accountNumber, bankCode, resolve]);

  const handleConfirm = useCallback(async () => {
    setBusy(true);
    setError(null);
    const failure = await onConfirm({ accountNumber, bankCode });
    setBusy(false);
    if (failure) {
      setError(failure.error);
      return;
    }
    setAccountName(null);
  }, [accountNumber, bankCode, onConfirm]);

  /** Drop the confirmed name so a corrected number is checked afresh. */
  const reset = useCallback(() => {
    setAccountName(null);
    setError(null);
  }, []);

  return (
    <div className="grid gap-4">
      {error ? (
        <p className="text-sm text-error" role="alert">
          {error}
        </p>
      ) : null}

      {accountName === null ? (
        <>
          <PaystackBankFields
            accountNumber={accountNumber}
            bankCode={bankCode}
            disabled={busy}
            idPrefix={idPrefix}
            loadBanks={loadBanks}
            onAccountNumberChange={(value) => {
              setAccountNumber(value);
              reset();
            }}
            onBankCodeChange={(value) => {
              setBankCode(value);
              reset();
            }}
          />
          <div>
            <Button
              disabled={busy || !paystackDetailsComplete(bankCode, accountNumber)}
              loading={busy}
              onClick={handleCheck}
              type="button"
            >
              Check account
            </Button>
          </div>
        </>
      ) : (
        <div className="grid gap-4 sm:max-w-md">
          <div className="rounded-xl border border-border-default bg-surface-2 p-5">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              This account belongs to
            </p>
            <p className="mt-2 font-heading text-lg font-bold text-foreground">
              {accountName}
            </p>
            <p className="mt-2 text-sm text-foreground-muted">
              Payouts will be sent here. If this is not the right name, the
              account number is wrong — money sent to it cannot be recovered.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button
              disabled={busy}
              loading={busy}
              onClick={handleConfirm}
              type="button"
            >
              {confirmLabel}
            </Button>
            <Button
              disabled={busy}
              onClick={reset}
              type="button"
              variant="secondary"
            >
              No, change the number
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
