"use client";

/**
 * Admin Treasury panel.
 *
 * Answers what an admin needs before moving platform money: how much belongs
 * to users, how much is the platform's own, how much can be withdrawn now, and
 * what has been withdrawn. Every admin can view; only the super-admin sees the
 * controls that move money or change where it goes (treasury decision 9). The
 * API enforces the same rule, so hiding the controls is convenience, not
 * security. Refetches when the tab regains focus because withdrawals settle by
 * webhook while the admin is away.
 *
 * Maps to: docs/superpowers/specs/2026-09-15-platform-treasury-design.md §Frontend.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { bankAccountOnHold } from "@/lib/financials/treasury";
import {
  adminPlatformBankAccountV1AdminTreasuryBankAccountGet as getBankAccount,
  adminPlatformWithdrawalsV1AdminTreasuryWithdrawalsGet as listWithdrawals,
  adminTreasurySummaryV1AdminTreasurySummaryGet as getSummary,
  adminUnrecognizedTransfersV1AdminTreasuryUnrecognizedTransfersGet as listTransfers,
} from "@/lib/generated/sdk.gen";
import type {
  PlatformBankAccountItem,
  PlatformWithdrawalItem,
  TreasurySummaryResponse,
  UnrecognizedTransferItem,
} from "@/lib/generated/types.gen";
import { useRefetchOnFocus } from "@/lib/hooks/use-refetch-on-focus";

import { BankAccountCard } from "./bank-account-card";
import { StatementCard } from "./statement-card";
import { LedgerOnlyCurrency, TreasuryFigures } from "./treasury-figures";
import { TreasuryWarnings } from "./treasury-warnings";
import { UnrecognizedTransfersList } from "./unrecognized-transfers-list";
import { WithdrawDialog } from "./withdraw-dialog";
import { WithdrawalsList } from "./withdrawals-list";

type TreasuryData = {
  summary: TreasurySummaryResponse;
  bankAccount: PlatformBankAccountItem | null;
  withdrawals: PlatformWithdrawalItem[];
  transfers: UnrecognizedTransferItem[];
};

/**
 * Render the Treasury page body.
 */
export function TreasuryPanel() {
  const [data, setData] = useState<TreasuryData | null>(null);
  const [isSuperadmin, setIsSuperadmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const latestRequest = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++latestRequest.current;
    configureBrowserClient();
    const headers = getAccessTokenHeaders();
    const [session, summary, bankAccount, withdrawals, transfers] = await Promise.all([
      loadCurrentUserSession(),
      getSummary({ headers }),
      getBankAccount({ headers }),
      listWithdrawals({ headers, query: { page: 1, page_size: 20 } }),
      listTransfers({ headers, query: { page: 1, page_size: 20 } }),
    ]);
    if (requestId !== latestRequest.current) {
      return;
    }
    setIsSuperadmin(session?.is_superadmin ?? false);
    const failedResult = [summary, bankAccount, withdrawals, transfers].find(
      (result) => !result.response.ok || !result.data,
    );
    if (failedResult) {
      setError(describeGeneratedError(failedResult.error));
      return;
    }
    setError(null);
    setData({
      summary: summary.data!,
      bankAccount: bankAccount.data!.bank_account ?? null,
      withdrawals: withdrawals.data!.withdrawals,
      transfers: transfers.data!.transfers,
    });
  }, []);

  useEffect(() => {
    void load();
    return () => {
      latestRequest.current += 1;
    };
  }, [load]);

  const refetch = useCallback(() => {
    void load();
  }, [load]);
  useRefetchOnFocus(refetch);

  if (error && !data) {
    return <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">{error}</p>;
  }
  if (!data) {
    return <TableSkeleton />;
  }

  const [paystackBlock, ...ledgerOnly] = data.summary.currencies;
  const inFlight = data.withdrawals.some(
    (withdrawal) => withdrawal.status === "pending" || withdrawal.status === "processing",
  );
  const canWithdraw =
    paystackBlock.withdrawable != null &&
    Number(paystackBlock.withdrawable) > 0 &&
    data.bankAccount != null &&
    !bankAccountOnHold(data.bankAccount, new Date()) &&
    !inFlight;

  return (
    <section className="grid gap-6">
      <header className="flex flex-col gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Admin treasury
          </p>
          <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Platform money
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            What the Paystack balance holds for users, what is the platform&apos;s own,
            and what can be withdrawn now.
            {isSuperadmin ? "" : " Only the super-admin can move money or change the bank account."}
          </p>
        </div>
        {isSuperadmin ? (
          <div className="grid gap-1">
            <Button disabled={!canWithdraw} onClick={() => setWithdrawOpen(true)}>
              Withdraw
            </Button>
            {inFlight ? (
              <p className="text-xs text-foreground-muted">A withdrawal is in progress.</p>
            ) : null}
          </div>
        ) : null}
      </header>

      <TreasuryWarnings
        bankAccount={data.bankAccount}
        block={paystackBlock}
        unreviewedTransfers={data.summary.unreviewed_unrecognized_transfers}
      />
      {notice ? (
        <p className="rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm text-success" role="status">
          {notice}
        </p>
      ) : null}

      <TreasuryFigures block={paystackBlock} />

      <UnrecognizedTransfersList
        canAcknowledge={isSuperadmin}
        onAcknowledged={refetch}
        transfers={data.transfers}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BankAccountCard
          account={data.bankAccount}
          canEdit={isSuperadmin}
          onChanged={refetch}
        />
        <StatementCard canBackfill={isSuperadmin} />
      </div>

      <WithdrawalsList withdrawals={data.withdrawals} />

      {ledgerOnly.length > 0 ? (
        <div className="grid gap-3">
          <h3 className="font-heading text-lg font-bold text-foreground">Other currencies</h3>
          {ledgerOnly.map((block) => (
            <LedgerOnlyCurrency block={block} key={block.currency} />
          ))}
        </div>
      ) : null}

      <WithdrawDialog
        bankAccount={data.bankAccount}
        currency={paystackBlock.currency}
        onClose={() => setWithdrawOpen(false)}
        onRequested={() => {
          setWithdrawOpen(false);
          setNotice("Withdrawal requested. It completes when Paystack confirms the transfer.");
          refetch();
        }}
        open={withdrawOpen}
        withdrawable={paystackBlock.withdrawable ?? "0"}
      />
    </section>
  );
}
