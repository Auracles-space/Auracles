/**
 * Treasury figure cards: the platform's money, users' money, what can be
 * withdrawn now, and the live Paystack balance.
 *
 * The withdrawable card leads because it is the number an admin acts on;
 * the two ledger cards expand to their lines so every total can be checked.
 * Currencies Paystack does not hold render as ledger-only.
 *
 * Maps to: platform treasury design §Frontend.
 */
import type { TreasuryCurrencySummary } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

const OUR_MONEY_LINES: { key: keyof TreasuryCurrencySummary["our_money"]; label: string; cost?: boolean }[] = [
  { key: "commission_framework_sales", label: "Commission: framework sales" },
  { key: "commission_collections", label: "Commission: collections" },
  { key: "commission_project_milestones", label: "Commission: project milestones" },
  { key: "commission_attestation_fees", label: "Commission: attestation fees" },
  { key: "provider_fees", label: "Paystack fees", cost: true },
  { key: "partner_commissions", label: "Partner commissions", cost: true },
  { key: "platform_withdrawals", label: "Platform withdrawals", cost: true },
];

const OWED_LINES: { key: keyof TreasuryCurrencySummary["owed_to_users"]; label: string }[] = [
  { key: "held_escrow", label: "Held in escrow" },
  { key: "contributor_balances", label: "Contributor balances" },
  { key: "org_balances", label: "Organization balances" },
  { key: "partner_commissions", label: "Unpaid partner commissions" },
];

/**
 * Render one labelled figure.
 *
 * @param label - What the figure is.
 * @param value - Formatted value, or an em dash when unknown.
 * @param testId - Stable test hook.
 * @param hint - Optional one-line explanation.
 * @param lead - Emphasises the figure an admin acts on.
 */
function Figure({
  label,
  value,
  testId,
  hint,
  lead = false,
}: {
  label: string;
  value: string;
  testId: string;
  hint?: string;
  lead?: boolean;
}) {
  return (
    <div
      className={[
        "rounded-2xl border p-5 shadow-sm",
        lead ? "border-accent/40 bg-surface-1" : "border-border-default bg-surface-1",
      ].join(" ")}
    >
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
        {label}
      </p>
      <p
        className="mt-2 font-heading text-3xl font-bold tracking-[-0.02em] text-foreground"
        data-testid={testId}
      >
        {value}
      </p>
      {hint ? <p className="mt-2 text-xs leading-5 text-foreground-muted">{hint}</p> : null}
    </div>
  );
}

/**
 * Render an expandable breakdown of one total.
 *
 * @param title - Breakdown heading.
 * @param lines - Label, amount and whether the amount is a cost.
 * @param currency - Currency the amounts are in.
 */
function Breakdown({
  title,
  lines,
  currency,
}: {
  title: string;
  lines: { label: string; amount: string; cost?: boolean }[];
  currency: string;
}) {
  return (
    <details className="rounded-xl border border-border-default bg-surface-2 p-4">
      <summary className="min-h-11 cursor-pointer text-sm font-semibold text-foreground">
        {title}
      </summary>
      <dl className="mt-3 grid gap-2">
        {lines.map((line) => (
          <div className="flex items-baseline justify-between gap-4 text-sm" key={line.label}>
            <dt className="text-foreground-muted">{line.label}</dt>
            <dd className="font-semibold tabular-nums text-foreground">
              {line.cost && Number(line.amount) > 0 ? "−" : ""}
              {formatMoney(line.amount, currency)}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/**
 * Render the figures for the currency Paystack holds.
 *
 * @param block - The withdrawable currency's summary.
 */
export function TreasuryFigures({ block }: { block: TreasuryCurrencySummary }) {
  const money = (amount: string | null) =>
    amount == null ? "—" : formatMoney(amount, block.currency);
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Figure
          hint="The smaller of our money and what the balance can spare after users are paid."
          label="Available to withdraw"
          lead
          testId="treasury-withdrawable"
          value={money(block.withdrawable)}
        />
        <Figure
          hint="Commission earned, less fees, partner commissions and withdrawals."
          label="Our money"
          testId="treasury-our-money"
          value={money(block.our_money.total)}
        />
        <Figure
          hint="Escrow and balances that belong to users."
          label="Owed to users"
          testId="treasury-owed-to-users"
          value={money(block.owed_to_users.total)}
        />
        <Figure
          hint="What Paystack holds right now."
          label="Paystack balance"
          testId="treasury-live-balance"
          value={money(block.live_balance)}
        />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Breakdown
          currency={block.currency}
          lines={OUR_MONEY_LINES.map((line) => ({
            label: line.label,
            amount: block.our_money[line.key],
            cost: line.cost,
          }))}
          title="How our money adds up"
        />
        <Breakdown
          currency={block.currency}
          lines={OWED_LINES.map((line) => ({
            label: line.label,
            amount: block.owed_to_users[line.key],
          }))}
          title="What users are owed"
        />
      </div>
    </div>
  );
}

/**
 * Render a ledger-only currency (settled on Stripe, not withdrawable here).
 *
 * @param block - The currency's summary.
 */
export function LedgerOnlyCurrency({ block }: { block: TreasuryCurrencySummary }) {
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-heading text-lg font-bold text-foreground">{block.currency}</h3>
        <span className="rounded-badge border border-border-default bg-surface-2 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-foreground-muted">
          Not withdrawable here
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        <div className="flex justify-between gap-4">
          <dt className="text-foreground-muted">Our money</dt>
          <dd className="font-semibold tabular-nums">
            {formatMoney(block.our_money.total, block.currency)}
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-foreground-muted">Owed to users</dt>
          <dd className="font-semibold tabular-nums">
            {formatMoney(block.owed_to_users.total, block.currency)}
          </dd>
        </div>
      </dl>
    </div>
  );
}
