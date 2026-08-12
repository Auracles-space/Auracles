"use client";

/**
 * Bank and account-number inputs for Paystack payout onboarding.
 *
 * Paystack has no hosted onboarding flow, so unlike Stripe Connect the NUBAN
 * details are collected in-app and registered as a transfer recipient. Shared
 * by the personal payout settings page and the organization surfaces so all of
 * them ask the same questions and validate them the same way.
 *
 * The bank list is fetched from the API rather than bundled: bank codes change
 * and new institutions appear, so a stale local copy would either reject a
 * valid account or address money to the wrong bank.
 *
 * Maps to: FR-FIN-* (payout onboarding, Nigerian corridor).
 */
import { useEffect, useState } from "react";

import { Select } from "@/components/ui/select";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { listPayoutBanks } from "@/lib/generated/sdk.gen";
import type { PayoutBank } from "@/lib/generated/types.gen";

/** NUBAN account numbers are always exactly ten digits. */
export const NUBAN_LENGTH = 10;

/**
 * Return whether a bank code and account number are complete enough to submit.
 *
 * @param bankCode - Selected Paystack bank code.
 * @param accountNumber - Digits entered so far.
 */
export function paystackDetailsComplete(
  bankCode: string,
  accountNumber: string,
): boolean {
  return bankCode !== "" && accountNumber.length === NUBAN_LENGTH;
}

/**
 * Render the bank selector and NUBAN input for Paystack payout onboarding.
 *
 * @param bankCode - Currently selected bank code.
 * @param accountNumber - Currently entered account number.
 * @param onBankCodeChange - Called with the newly selected bank code.
 * @param onAccountNumberChange - Called with the digits-only account number.
 * @param idPrefix - Prefix for input ids, so two instances can coexist.
 * @param disabled - Disables both inputs while a submission is in flight.
 */
export function PaystackBankFields({
  bankCode,
  accountNumber,
  onBankCodeChange,
  onAccountNumberChange,
  idPrefix = "payout",
  disabled = false,
}: {
  bankCode: string;
  accountNumber: string;
  onBankCodeChange: (value: string) => void;
  onAccountNumberChange: (value: string) => void;
  idPrefix?: string;
  disabled?: boolean;
}) {
  const [banks, setBanks] = useState<PayoutBank[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadBanks() {
      const result = await listPayoutBanks({ headers: getAccessTokenHeaders() });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setBanks(result.data.banks);
    }

    void loadBanks();
  }, []);

  return (
    <div className="grid gap-4 sm:max-w-md">
      {error ? <p className="text-sm text-error">{error}</p> : null}
      <div>
        <label
          className="mb-1 block text-sm font-semibold text-foreground"
          htmlFor={`${idPrefix}-bank`}
        >
          Bank
        </label>
        <Select
          disabled={disabled}
          id={`${idPrefix}-bank`}
          onChange={(event) => onBankCodeChange(event.target.value)}
          value={bankCode}
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
          className="mb-1 block text-sm font-semibold text-foreground"
          htmlFor={`${idPrefix}-account-number`}
        >
          Account number
        </label>
        <input
          className="flex min-h-12 w-full rounded-xl border border-border-default bg-surface-1 px-3 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
          disabled={disabled}
          id={`${idPrefix}-account-number`}
          inputMode="numeric"
          maxLength={NUBAN_LENGTH}
          onChange={(event) =>
            onAccountNumberChange(event.target.value.replace(/\D/g, ""))
          }
          placeholder="0123456789"
          value={accountNumber}
        />
        <p className="mt-1 text-xs text-foreground-muted">
          The {NUBAN_LENGTH}-digit NUBAN account number. We confirm the account
          name with the bank before any payout is sent.
        </p>
      </div>
    </div>
  );
}
