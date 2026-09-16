/**
 * Platform withdrawal history.
 *
 * Stacked cards on mobile, a table from `md:` up. Destinations show as bank
 * and last four digits only; a failed withdrawal shows Paystack's reason.
 *
 * Maps to: platform treasury design §Frontend.
 */
import { formatTimestamp, Pill, toneForStatus } from "@/components/modules/admin/admin-money-primitives";
import type { PlatformWithdrawalItem } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

/**
 * Render a withdrawal's status, naming an OTP hold instead of "processing".
 *
 * @param withdrawal - The withdrawal.
 */
function WithdrawalStatus({ withdrawal }: { withdrawal: PlatformWithdrawalItem }) {
  if (withdrawal.status === "processing" && withdrawal.awaiting_otp) {
    return <Pill tone="warning">Waiting for OTP</Pill>;
  }
  return <Pill tone={toneForStatus(withdrawal.status)}>{withdrawal.status}</Pill>;
}

/**
 * Render the withdrawal history.
 *
 * @param withdrawals - Withdrawals, newest first.
 */
export function WithdrawalsList({ withdrawals }: { withdrawals: PlatformWithdrawalItem[] }) {
  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h3 className="font-heading text-lg font-bold text-foreground">Withdrawals</h3>
      {withdrawals.length === 0 ? (
        <p className="mt-3 text-sm text-foreground-muted">No platform withdrawals yet.</p>
      ) : (
        <>
          <ul className="mt-4 grid gap-3 md:hidden">
            {withdrawals.map((withdrawal) => (
              <li
                className="grid gap-1 rounded-xl border border-border-default bg-surface-2 p-4 text-sm"
                key={withdrawal.id}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-semibold tabular-nums">
                    {formatMoney(withdrawal.amount, withdrawal.currency)}
                  </span>
                  <WithdrawalStatus withdrawal={withdrawal} />
                </div>
                <span className="text-foreground-muted">
                  {withdrawal.bank_name} ****{withdrawal.account_last4}
                </span>
                <span className="text-foreground-muted">
                  {formatTimestamp(withdrawal.requested_at)}
                </span>
                {withdrawal.failure_reason ? (
                  <span className="text-error">{withdrawal.failure_reason}</span>
                ) : null}
              </li>
            ))}
          </ul>
          <table className="mt-4 hidden w-full text-left text-sm md:table">
            <thead className="text-xs uppercase tracking-[0.05em] text-foreground-muted">
              <tr>
                <th className="py-2 font-semibold">Requested</th>
                <th className="py-2 font-semibold">Amount</th>
                <th className="py-2 font-semibold">Destination</th>
                <th className="py-2 font-semibold">Status</th>
                <th className="py-2 font-semibold">Reference</th>
              </tr>
            </thead>
            <tbody>
              {withdrawals.map((withdrawal) => (
                <tr className="border-t border-border-default align-top" key={withdrawal.id}>
                  <td className="py-3">{formatTimestamp(withdrawal.requested_at)}</td>
                  <td className="py-3 font-semibold tabular-nums">
                    {formatMoney(withdrawal.amount, withdrawal.currency)}
                  </td>
                  <td className="py-3">
                    {withdrawal.bank_name} ****{withdrawal.account_last4}
                  </td>
                  <td className="py-3">
                    <WithdrawalStatus withdrawal={withdrawal} />
                    {withdrawal.failure_reason ? (
                      <p className="mt-1 text-xs text-error">{withdrawal.failure_reason}</p>
                    ) : null}
                  </td>
                  <td className="py-3 font-mono text-xs text-foreground-muted">
                    {withdrawal.reference}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
