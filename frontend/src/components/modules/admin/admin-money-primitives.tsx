/**
 * Shared presentation primitives for the admin money-oversight surface.
 *
 * Extracted so the panel and the payment-trace view render identical pills,
 * amounts, and timestamps: an admin comparing a list row against a timeline
 * entry must not have to reconcile two formats.
 *
 * Maps to: admin financial oversight (money movement traceability).
 */

/** Tabs across the money-oversight surface, in investigation order. */
export const MONEY_TABS = [
  { id: "payments", label: "Payments" },
  { id: "ledger", label: "Ledger" },
  { id: "escrows", label: "Escrows" },
  { id: "webhooks", label: "Webhooks" },
  { id: "audit", label: "Audit log" },
] as const;

export type MoneyTab = (typeof MONEY_TABS)[number]["id"];

/** Provider filter options shared by every provider-aware view. */
export const PROVIDER_OPTIONS = [
  { value: "all", label: "All providers" },
  { value: "paystack", label: "Paystack" },
  { value: "stripe", label: "Stripe" },
];

type Tone = "default" | "success" | "warning" | "error";

const TONE_STYLES: Record<Tone, string> = {
  default: "border-border-default bg-surface-2 text-foreground-muted",
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  error: "border-error/30 bg-error/10 text-error",
};

/**
 * Map a money status onto a semantic tone.
 *
 * Covers transaction, escrow, and webhook vocabularies together: they share
 * this surface, and an admin reads colour before text.
 *
 * @param status - Status string from any money-oversight response.
 * @returns The tone to render the status pill with.
 */
export function toneForStatus(status: string): Tone {
  if (status === "completed" || status === "processed" || status === "released") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  if (status === "pending" || status === "received" || status === "held") {
    return "warning";
  }
  return "default";
}

/**
 * Format an ISO timestamp for compact admin copy.
 *
 * @param value - ISO timestamp string.
 * @returns A locale-formatted date and time, or the raw value if unparseable.
 */
export function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Format a decimal amount string as a currency value.
 *
 * @param amount - Decimal string from the API (e.g. "450.00").
 * @param currency - ISO 4217 currency code.
 * @returns A localized currency string, falling back to the raw pair.
 */
export function formatAmount(amount: string, currency: string): string {
  const value = Number(amount);
  if (Number.isNaN(value)) {
    return `${amount} ${currency}`;
  }
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
    }).format(value);
  } catch {
    return `${amount} ${currency}`;
  }
}

/**
 * Render a compact status or label pill.
 *
 * @param props.children - Pill text.
 * @param props.tone - Semantic tone; defaults to neutral.
 */
export function Pill({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  return (
    <span
      className={[
        "inline-flex w-fit items-center rounded-badge border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
        TONE_STYLES[tone],
      ].join(" ")}
    >
      {children}
    </span>
  );
}

/**
 * Render a single headline figure.
 *
 * @param props.label - Figure caption.
 * @param props.value - Figure value, pre-formatted.
 * @param props.tone - Semantic tone applied to the value.
 */
export function StatCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: Tone;
}) {
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
        {label}
      </p>
      <p
        className={[
          "mt-1 font-heading text-2xl font-bold",
          tone === "error" ? "text-error" : "text-foreground",
        ].join(" ")}
      >
        {value}
      </p>
    </div>
  );
}

/**
 * Render a labelled select filter.
 *
 * @param props.label - Visible field label.
 * @param props.value - Current value.
 * @param props.options - Selectable options.
 * @param props.onChange - Called with the newly selected value.
 */
export function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-2 text-sm font-semibold text-foreground">
      {label}
      <select
        className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * Render an empty-result placeholder.
 *
 * @param props.message - Explanation of why nothing is shown.
 */
export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-8 text-center text-sm text-foreground-muted shadow-sm">
      {message}
    </div>
  );
}

/**
 * Render a request-failure banner.
 *
 * @param props.message - Human-readable error description.
 */
export function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error"
      role="alert"
    >
      {message}
    </div>
  );
}
