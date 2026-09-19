"use client";

/**
 * Platform bank account card.
 *
 * Every admin sees where platform money goes: bank, last four digits and the
 * bank-confirmed account name. Only the super-admin can change it; a change
 * needs step-up, is announced to all admins, and holds withdrawals for 24
 * hours, which the copy states before the change is made.
 *
 * Setting an account names its holder first and waits for acceptance, the
 * same question the Contributor and organization surfaces ask. The 24-hour
 * hold would catch a mistyped number eventually, but only if somebody
 * re-reads the card; the name is the moment the mistake is actually visible.
 *
 * Maps to: platform treasury design, decision 3.
 */
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import type { BankListLoader } from "@/components/modules/financials/paystack-bank-fields";
import {
  type BankDetails,
  ConfirmBankAccount,
  type ResolveResult,
} from "@/components/modules/financials/confirm-bank-account";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  adminSetPlatformBankAccountV1AdminTreasuryBankAccountPut as setBankAccount,
  adminTreasuryBanksV1AdminTreasuryBanksGet as listTreasuryBanks,
  adminTreasuryResolveAccountV1AdminTreasuryResolveAccountPost as resolveTreasuryAccount,
} from "@/lib/generated/sdk.gen";
import type { PlatformBankAccountItem } from "@/lib/generated/types.gen";

/**
 * Load banks from the Treasury API. The Contributor list requires the
 * Contributor role, and its refusal reads as unfinished onboarding.
 */
const loadTreasuryBanks: BankListLoader = () =>
  listTreasuryBanks({ headers: getAccessTokenHeaders() });

/**
 * Render the bank account card.
 *
 * @param account - The active account, or null before one is set.
 * @param canEdit - Whether the viewer is the super-admin.
 * @param onChanged - Called after the account was saved.
 */
export function BankAccountCard({
  account,
  canEdit,
  onChanged,
}: {
  account: PlatformBankAccountItem | null;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);

  /** Ask the bank who holds an account, registering nothing. */
  const resolve = useCallback(
    async ({ accountNumber, bankCode }: BankDetails): Promise<ResolveResult> => {
      configureBrowserClient();
      const result = await resolveTreasuryAccount({
        headers: getAccessTokenHeaders(),
        body: { account_number: accountNumber, bank_code: bankCode },
      });
      if (!result.response.ok || !result.data) {
        return { error: describeGeneratedError(result.error) };
      }
      return { name: result.data.account_name };
    },
    [],
  );

  /** Set the platform account once its holder has been accepted. */
  const confirm = useCallback(
    async ({ accountNumber, bankCode }: BankDetails) => {
      configureBrowserClient();
      const result = await setBankAccount({
        headers: getAccessTokenHeaders(),
        body: { account_number: accountNumber, bank_code: bankCode },
      });
      if (!result.response.ok) {
        return { error: describeGeneratedError(result.error) };
      }
      setEditing(false);
      onChanged();
      return null;
    },
    [onChanged],
  );

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h3 className="font-heading text-lg font-bold text-foreground">Platform bank account</h3>
      {account ? (
        <dl className="mt-3 grid gap-1 text-sm">
          <dd className="font-semibold text-foreground">
            {account.bank_name} ****{account.account_last4}
          </dd>
          <dd className="text-foreground-muted">{account.account_name ?? "Name not confirmed"}</dd>
        </dl>
      ) : (
        <p className="mt-3 text-sm text-foreground-muted">
          No bank account is set, so platform money cannot be withdrawn yet.
        </p>
      )}
      {canEdit && !editing ? (
        <Button className="mt-4" onClick={() => setEditing(true)} variant="secondary">
          {account ? "Change account" : "Set bank account"}
        </Button>
      ) : null}
      {canEdit && editing ? (
        <div className="mt-4 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4">
          <p className="text-sm leading-6 text-foreground-muted">
            Paystack confirms the account name with the bank. Withdrawals to a new
            account open 24 hours after the change, and every admin is notified.
          </p>
          <ConfirmBankAccount
            confirmLabel="Yes, use this account"
            idPrefix="treasury-bank"
            loadBanks={loadTreasuryBanks}
            onConfirm={confirm}
            resolve={resolve}
          />
          <div>
            <Button onClick={() => setEditing(false)} variant="secondary">
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
