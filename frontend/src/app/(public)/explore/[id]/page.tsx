/**
 * Public Framework detail route.
 *
 * Server-rendered so public Framework pages are indexable and preview metadata
 * is visible to incomplete users without granting download access.
 */
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  AttestationBadge,
  ReviewSummary,
} from "@/components/modules/explore/framework-card";
import { FrameworkLicenseCta } from "@/components/modules/explore/framework-license-cta";
import { PreviewArtifactBlock } from "@/components/modules/explore/preview-artifact-block";
import { RelatedFrameworks } from "@/components/modules/explore/related-frameworks";
import { RarityBadge } from "@/components/modules/frameworks/rarity-badge";
import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";
import { BackButton } from "@/components/ui/back-button";
import {
  getExploreFrameworkDetail,
  getRelatedExploreFrameworks,
} from "@/lib/generated/sdk.gen";
import type { ExploreFrameworkDetail } from "@/lib/generated/types.gen";
import { rarityBadge } from "@/lib/rarity";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type ExploreDetailPageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render a public Framework detail page.
 *
 * @param props - Next.js route params.
 */
export default async function ExploreDetailPage({
  params,
}: ExploreDetailPageProps) {
  const { id } = await params;

  configureServerMarketplaceClient();
  const [detailResult, relatedResult] = await Promise.all([
    getExploreFrameworkDetail({ path: { framework_id: id } }),
    getRelatedExploreFrameworks({ path: { framework_id: id } }),
  ]);

  if (!detailResult.response.ok || !detailResult.data) {
    notFound();
  }

  const framework: ExploreFrameworkDetail = detailResult.data;
  const related = relatedResult.data ?? [];

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <BackButton fallbackHref="/explore">
          Back to Explore
        </BackButton>
        <div className="mt-6 grid gap-8 lg:grid-cols-[1fr_360px] lg:items-start min-w-0">
          <section className="min-w-0 rounded-2xl border border-border-default bg-surface-1 p-6 md:p-10 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              {formatLabel(framework.category)}
            </p>
            <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-5xl">
              {framework.title}
            </h1>
            <p className="mt-4 max-w-3xl text-base leading-7 text-foreground-muted">
              {framework.description}
            </p>
            <Link
              className="mt-4 inline-flex min-h-12 items-center text-sm font-semibold text-accent transition hover:text-accent/80"
              href={`/profile/${framework.contributor_id}`}
            >
              {framework.contributor_name}
            </Link>
            <div className="mt-6 flex flex-wrap gap-2">
              {framework.reputation ? (
                <ReputationBadge
                  score={framework.reputation.score ?? null}
                  isProvisional={framework.reputation.is_provisional ?? true}
                  factors={framework.reputation.factors ?? []}
                />
              ) : null}
              {framework.attestation_badge ? (
                <AttestationBadge badge={framework.attestation_badge} />
              ) : null}
              {framework.tags.map((tag: string) => (
                <span
                  className="rounded-md border border-border-default px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted"
                  key={tag}
                >
                  {tag}
                </span>
              ))}
            </div>
          </section>
          <aside className="min-w-0 sticky top-8 rounded-2xl border border-border-default bg-surface-2 p-6 shadow-sm">
            <p className="text-sm text-foreground-muted">Starting price</p>
            <p className="mt-1 font-heading text-4xl font-bold text-foreground">
              {formatMoney(framework.price, framework.currency)}
            </p>
            {framework.license_types.includes("organizational") ? (
              <div className="mt-3">
                <p className="text-sm text-foreground-muted">Organizational</p>
                <p className="text-lg font-semibold text-foreground">
                  {framework.org_price != null
                    ? formatMoney(framework.org_price, framework.currency)
                    : `${formatMoney(framework.price, framework.currency)} — same as single user`}
                </p>
              </div>
            ) : null}
            
            <div className="mt-6 grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-border-default bg-surface-1 p-3">
                <p className="text-[11px] uppercase tracking-wider text-foreground-muted">Version</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{framework.version}</p>
              </div>
              <div className="rounded-xl border border-border-default bg-surface-1 p-3">
                <p className="text-[11px] uppercase tracking-wider text-foreground-muted">Complexity</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{framework.complexity ?? "Not set"}</p>
              </div>
              {rarityBadge(framework.rarity_score) ? (
                <div className="rounded-xl border border-border-default bg-surface-1 p-3">
                  <p className="text-[11px] uppercase tracking-wider text-foreground-muted">Rarity</p>
                  <p className="mt-1">
                    <RarityBadge score={framework.rarity_score} />
                  </p>
                </div>
              ) : null}
              <div className="rounded-xl border border-border-default bg-surface-1 p-3">
                <p className="text-[11px] uppercase tracking-wider text-foreground-muted">Organization</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{formatLabel(framework.org_size)}</p>
              </div>
              <div className="col-span-2 flex items-center justify-between rounded-xl border border-border-default bg-surface-1 p-3">
                <span className="text-[11px] uppercase tracking-wider text-foreground-muted">Reviews</span>
                <span className="text-sm font-semibold text-foreground">
                  <ReviewSummary
                    averageScore={framework.average_review_score ?? null}
                    reviewCount={framework.review_count ?? 0}
                  />
                </span>
              </div>
            </div>
            
            <FrameworkLicenseCta
              contributorId={framework.contributor_id ?? ""}
              frameworkId={framework.id}
            />
          </aside>
        </div>
        <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_360px] lg:items-start min-w-0">
          <div className="min-w-0">
            <PreviewArtifactBlock framework={framework} />
          </div>
          <section className="min-w-0 rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
            <h2 className="font-heading text-lg font-bold text-foreground">
              Trust signals
            </h2>
            <ul className="mt-4 grid gap-3 text-sm text-foreground-muted break-words">
              {framework.attestation_badge ? (
                <li>
                  Attestation outcome:{" "}
                  {formatLabel(framework.attestation_badge.outcome)} (
                  {formatLabel(framework.attestation_badge.status)}).
                </li>
              ) : (
                <li>No public Attestation report has been attached yet.</li>
              )}
              <li>
                Reviews: {framework.average_review_score ?? "No average yet"} from{" "}
                {framework.review_count} review
                {framework.review_count === 1 ? "" : "s"}.
              </li>
              <li>Published version snapshot preserved for licensees.</li>
              <li>Artifact previews use short-lived read URLs.</li>
              <li>Licensed downloads require Operator role and verified KYC.</li>
            </ul>
          </section>
        </div>
        <div className="mt-10">
          <RelatedFrameworks frameworks={related} />
        </div>
      </div>
    </main>
  );
}
