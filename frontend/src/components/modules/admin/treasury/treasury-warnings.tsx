/**
 * Treasury warnings band.
 *
 * Surfaces, above every figure, the conditions that mean the numbers or the
 * money cannot be taken at face value: the live balance is short of the
 * ledger, Paystack could not be reached, a withdrawal is held for an OTP, a
 * transfer left the balance outside Auracles, or the bank account was changed
 * less than 24 hours ago.
 *
 * Maps to: platform treasury design, decisions 3 and 5.
 */
import type {
  PlatformBankAccountItem,
  TreasuryCurrencySummary,
} from "@/lib/generated/types.gen";
import { bankAccountOnHold, isNegativeAmount } from "@/lib/financials/treasury";
import { formatMoney } from "@/lib/marketplace/format";

type Tone = "error" | "warning" | "info";

const TONE: Record<Tone, string> = {
  error: "border-error/30 bg-error/10 text-error",
  warning: "border-warning/30 bg-warning/10 text-warning",
  info: "border-info/30 bg-info/10 text-info",
};

/**
 * Render every warning that applies, or nothing.
 *
 * @param block - The withdrawable currency's summary.
 * @param unreviewedTransfers - Transfers not started by Auracles, unreviewed.
 * @param bankAccount - The active platform bank account, if any.
 * @param withdrawalAwaitingOtp - A withdrawal Paystack is holding for an OTP.
 */
export function TreasuryWarnings({
  block,
  unreviewedTransfers,
  bankAccount,
  withdrawalAwaitingOtp = false,
}: {
  block: TreasuryCurrencySummary;
  unreviewedTransfers: number;
  bankAccount: PlatformBankAccountItem | null;
  withdrawalAwaitingOtp?: boolean;
}) {
  const warnings: { tone: Tone; text: string }[] = [];
  if (block.balance_unavailable) {
    warnings.push({
      tone: "warning",
      text: "Paystack balance is unavailable, so nothing can be withdrawn right now. Ledger figures below are still current.",
    });
  }
  if (isNegativeAmount(block.balance_gap) && block.balance_gap) {
    const missing = formatMoney(String(Math.abs(Number(block.balance_gap))), block.currency);
    warnings.push({
      tone: "error",
      text: `Paystack holds ${missing} less than the ledger says it should. Check recent transfers and fees before withdrawing.`,
    });
  }
  if (withdrawalAwaitingOtp) {
    warnings.push({
      tone: "warning",
      text: "A withdrawal is waiting for a Paystack OTP and will not be sent until someone enters it. Finalize it in the Paystack dashboard, or turn off transfer OTP under Settings, Preferences, Transfers.",
    });
  }
  if (unreviewedTransfers > 0) {
    warnings.push({
      tone: "error",
      text: `${unreviewedTransfers} transfer${unreviewedTransfers === 1 ? "" : "s"} not started by Auracles ${unreviewedTransfers === 1 ? "needs" : "need"} review. See the list below.`,
    });
  }
  if (bankAccount && bankAccountOnHold(bankAccount, new Date())) {
    const opens = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "Africa/Lagos",
    }).format(new Date(bankAccount.usable_from));
    warnings.push({
      tone: "info",
      text: `The bank account was changed recently. Withdrawals to this account open ${opens} (Lagos time).`,
    });
  }
  if (warnings.length === 0) {
    return null;
  }
  return (
    <ul aria-label="Treasury warnings" className="grid gap-3">
      {warnings.map((warning) => (
        <li
          className={["rounded-xl border px-4 py-3 text-sm leading-6", TONE[warning.tone]].join(" ")}
          key={warning.text}
          role={warning.tone === "error" ? "alert" : "status"}
        >
          {warning.text}
        </li>
      ))}
    </ul>
  );
}
