/**
 * Public Explore Framework card.
 *
 * Cards expose trust signals and pricing without leaking private artifact keys.
 */
import { CheckCircledIcon, ClockIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import type {
  ExploreAttestationBadge,
  ExploreFrameworkCard,
} from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type FrameworkCardProps = {
  framework: ExploreFrameworkCard;
};

/**
 * Render a compact public Attestation trust badge.
 *
 * @param props - Public badge data from the Explore API.
 */
export function AttestationBadge({
  badge,
}: {
  badge: ExploreAttestationBadge;
}) {
  const isPending = badge.status === "pending_acceptance";
  const Icon = isPending ? ClockIcon : CheckCircledIcon;
  const className = isPending
    ? "border-warning/30 bg-warning/10 text-warning"
    : "border-success/30 bg-success/10 text-success";
  const label = isPending ? "Pending acceptance" : "Attested";

  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1",
        "text-[11px] font-semibold uppercase tracking-[0.05em]",
        className,
      ].join(" ")}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label}: {formatLabel(badge.outcome)}
    </span>
  );
}

/**
 * Render one marketplace catalog item.
 *
 * @param props - Public Framework summary.
 */
export function FrameworkCard({ framework }: FrameworkCardProps) {
  return (
    <article className="group relative flex flex-col justify-between overflow-hidden rounded-2xl border border-border-default bg-surface-1 p-5 shadow-bento transition duration-300 hover:-translate-y-1 hover:border-accent/50 hover:shadow-hero">
      <div>
        <div className="mb-3 flex items-start justify-between gap-4">
          <h2 className="font-heading text-lg font-semibold leading-tight text-foreground group-hover:text-accent transition-colors">
            <Link href={`/explore/${framework.id}`} className="focus:outline-none">
              <span className="absolute inset-0" aria-hidden="true" />
              {framework.title}
            </Link>
          </h2>
          <div className="text-right">
            <strong className="font-heading text-lg font-bold text-foreground">
              {formatMoney(framework.price, framework.currency)}
            </strong>
          </div>
        </div>
        <p className="line-clamp-2 text-sm leading-6 text-foreground-muted">
          {framework.description}
        </p>
      </div>

      <div className="mt-6 flex flex-col gap-4">
        {/* Tags */}
        <div className="flex flex-wrap gap-2">
          <span className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
            {formatLabel(framework.category)}
          </span>
          <span className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
            {formatLabel(framework.org_size)}
          </span>
          {framework.license_types.slice(0, 1).map((license) => (
            <span
              className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted"
              key={license}
            >
              {formatLabel(license)}
            </span>
          ))}
          {framework.owned && (
            <span className="rounded-md border border-info/30 bg-info/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-info">
              Owned
            </span>
          )}
          {framework.attestation_badge ? (
            <AttestationBadge badge={framework.attestation_badge} />
          ) : null}
        </div>

        {/* Footer / Meta */}
        <div className="flex items-center justify-between border-t border-border-default pt-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-foreground-muted">
              v{framework.version}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-foreground-muted transition-colors group-hover:text-foreground">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            Preview
          </div>
        </div>
      </div>
    </article>
  );
}
