/**
 * Public Explore Framework card.
 *
 * Cards expose trust signals and pricing without leaking private artifact keys.
 */
import { CheckCircledIcon, InfoCircledIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import type {
  ExploreAttestationBadge,
  ExploreCollectionCard,
  ExploreFrameworkCard,
} from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";
import { RatingStars } from "@/components/modules/reputation/rating-stars";

type FrameworkCardProps = {
  framework: ExploreFrameworkCard;
};

type CollectionCardProps = {
  collection: ExploreCollectionCard;
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
  // Only accepted attestations reach a public badge; a pending report shows no
  // badge at all, so the two positive states are the only ones handled here.
  const statusConfig = {
    attested: {
      className: "border-success/30 bg-success/10 text-success",
      icon: CheckCircledIcon,
      label: "Attested",
    },
    conditionally_attested: {
      className: "border-info/30 bg-info/10 text-info",
      icon: InfoCircledIcon,
      label: "Conditional",
    },
  }[badge.status];
  const Icon = statusConfig.icon;
  const attestationCount = badge.attestation_count ?? 0;
  const reportLabel =
    attestationCount > 1 ? ` · ${attestationCount} reports` : "";

  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1",
        "text-[11px] font-semibold uppercase tracking-[0.05em]",
        statusConfig.className,
      ].join(" ")}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {statusConfig.label}: {formatLabel(badge.outcome)}
      {reportLabel}
    </span>
  );
}

/**
 * Render public review aggregate text for a Framework card or detail page.
 *
 * @param props - Average score and count from the Explore API.
 */
export function ReviewSummary({
  averageScore,
  reviewCount,
}: {
  averageScore: string | null;
  reviewCount: number;
}) {
  if (!averageScore) {
    return (
      <span className="inline-flex items-center text-xs font-semibold text-foreground-muted">
        No reviews yet
      </span>
    );
  }

  const numericScore = parseFloat(averageScore);

  return (
    <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground-muted">
      <RatingStars rating={numericScore} starClassName="h-3.5 w-3.5" />
      <span>
        ({reviewCount})
      </span>
    </div>
  );
}

/**
 * Render one marketplace catalog item.
 *
 * @param props - Public Framework summary.
 */
export function FrameworkCard({ framework }: FrameworkCardProps) {
  return (
    <article className="group relative flex flex-col justify-between overflow-hidden rounded-2xl border border-border-default bg-surface-1 p-6 shadow-bento transition-all duration-300 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-card">
      <div className="flex-1 flex flex-col">
        {/* Category Header */}
        <span className="text-[10px] font-bold uppercase tracking-wider text-accent mb-2.5 block">
          {formatLabel(framework.category)}
        </span>

        {/* Title & Price Row */}
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 
            className="font-heading text-lg font-semibold leading-snug text-foreground group-hover:text-accent transition-colors line-clamp-2"
            title={framework.title}
          >
            <Link
              href={`/explore/${framework.id}`}
              className="focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {framework.title}
            </Link>
          </h2>
          <div className="text-right flex-shrink-0 pt-0.5">
            <strong className="font-heading text-lg font-bold text-foreground">
              {formatMoney(framework.price, framework.currency)}
            </strong>
          </div>
        </div>

        {/* Description */}
        <p className="line-clamp-2 text-sm leading-relaxed text-foreground-muted mb-4 flex-1">
          {framework.description}
        </p>

        {/* Contributor & Trust Row */}
        <div className="mt-auto border-t border-border-default/50 pt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex items-center text-xs font-semibold text-foreground">
            <span className="text-foreground-subtle font-normal mr-1">By</span>
            <Link
              className="hover:text-accent transition-colors"
              href={`/profile/${framework.contributor_id}`}
            >
              {framework.contributor_name}
            </Link>
          </div>
          
          <div className="flex items-center gap-2">
            <ReviewSummary
              averageScore={framework.average_review_score ?? null}
              reviewCount={framework.review_count ?? 0}
            />
            {framework.reputation ? (
              <ReputationBadge
                score={framework.reputation.score ?? null}
                isProvisional={framework.reputation.is_provisional ?? true}
                factors={framework.reputation.factors ?? []}
              />
            ) : null}
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-col gap-4">
        {/* Tags */}
        <div className="flex flex-wrap gap-2">
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
          <Link
            href={`/explore/${framework.id}`}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-foreground-muted transition-colors hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent group-hover:text-foreground"
            aria-label={`Preview ${framework.title}`}
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            Preview
          </Link>
        </div>
      </div>
    </article>
  );
}

/**
 * Render one public Collection catalog item.
 *
 * @param props - Public Collection summary.
 */
export function CollectionCard({ collection }: CollectionCardProps) {
  return (
    <article className="group relative flex flex-col justify-between overflow-hidden rounded-2xl border border-border-default bg-surface-1 p-6 shadow-bento transition-all duration-300 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-card">
      <div className="flex-1 flex flex-col">
        {/* Collection Header */}
        <span className="text-[10px] font-bold uppercase tracking-wider text-info mb-2.5 block">
          Collection Bundle
        </span>

        {/* Title & Price Row */}
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 
            className="font-heading text-lg font-semibold leading-snug text-foreground transition-colors group-hover:text-accent line-clamp-2"
            title={collection.title}
          >
            <Link
              href={`/explore/collections/${collection.id}`}
              className="focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {collection.title}
            </Link>
          </h2>
          <div className="text-right flex-shrink-0 pt-0.5">
            <strong className="font-heading text-lg font-bold text-foreground">
              {formatMoney(collection.bundle_price, collection.currency)}
            </strong>
          </div>
        </div>

        {/* Description */}
        <p className="line-clamp-2 text-sm leading-relaxed text-foreground-muted mb-4 flex-1">
          {collection.description}
        </p>

        {/* Contributor Row */}
        <div className="mt-auto border-t border-border-default/50 pt-4 flex items-center justify-between gap-3">
          <div className="inline-flex items-center text-xs font-semibold text-foreground">
            <span className="text-foreground-subtle font-normal mr-1">By</span>
            <Link
              className="hover:text-accent transition-colors"
              href={`/profile/${collection.contributor_id}`}
            >
              {collection.contributor_name}
            </Link>
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-col gap-4">
        {/* Info badges */}
        <div className="flex flex-wrap gap-2">
          <span className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
            {collection.member_count} frameworks
          </span>
          <span className="rounded-md border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-success">
            Save {formatMoney(collection.savings_amount, collection.currency)}
          </span>
          <span className="rounded-md border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-success">
            {collection.savings_percent}% off
          </span>
        </div>

        {/* Members list */}
        <div className="grid gap-2">
          {collection.members.slice(0, 3).map((member) => (
            <div
              className="rounded-xl border border-border-default bg-surface-2 px-3 py-2 text-xs text-foreground-muted flex items-center justify-between"
              key={member.framework_id}
            >
              <div>
                <span className="font-semibold text-foreground">{member.title}</span>
                <span className="text-foreground-subtle"> · </span>
                <span className="text-foreground-subtle text-[10px] uppercase font-medium tracking-wider">{formatLabel(member.category)}</span>
              </div>
              <span className="text-xs font-medium text-foreground">{formatMoney(member.price, member.currency)}</span>
            </div>
          ))}
        </div>

        {/* Footer / Meta */}
        <div className="flex items-center justify-between border-t border-border-default pt-4">
          <span className="text-xs font-medium text-foreground-muted">
            Member value {formatMoney(collection.member_price_sum, collection.currency)}
          </span>
          <span className="text-xs font-semibold text-accent">View bundle</span>
        </div>
      </div>
    </article>
  );
}
