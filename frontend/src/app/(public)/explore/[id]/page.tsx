/**
 * Public Framework detail route.
 *
 * Server-rendered so public Framework pages are indexable and preview metadata
 * is visible to incomplete users without granting download access.
 */
import Link from "next/link";
import { notFound } from "next/navigation";

import { PreviewArtifactBlock } from "@/components/modules/explore/preview-artifact-block";
import { RelatedFrameworks } from "@/components/modules/explore/related-frameworks";
import {
  getExploreFrameworkDetail,
  getRelatedExploreFrameworks,
} from "@/lib/generated/sdk.gen";
import type { ExploreFrameworkDetail } from "@/lib/generated/types.gen";
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
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <Link className="text-sm font-semibold text-accent" href="/explore">
          Back to Explore
        </Link>
        <div className="mt-6 grid gap-8 lg:grid-cols-[1fr_360px]">
          <section>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              {formatLabel(framework.category)}
            </p>
            <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-5xl">
              {framework.title}
            </h1>
            <p className="mt-4 max-w-3xl text-base leading-7 text-foreground-muted">
              {framework.description}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {framework.tags.map((tag: string) => (
                <span
                  className="rounded-[4px] border border-border-default px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted"
                  key={tag}
                >
                  {tag}
                </span>
              ))}
            </div>
          </section>
          <aside className="rounded-[8px] border border-border-default bg-surface-2 p-5">
            <p className="text-sm text-foreground-muted">Starting price</p>
            <p className="mt-1 font-heading text-3xl font-bold text-foreground">
              {formatMoney(framework.price, framework.currency)}
            </p>
            <dl className="mt-5 grid gap-3 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Version</dt>
                <dd className="font-semibold text-foreground">{framework.version}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Organization</dt>
                <dd className="font-semibold text-foreground">
                  {formatLabel(framework.org_size)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Complexity</dt>
                <dd className="font-semibold text-foreground">
                  {framework.complexity ?? "Not set"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Rarity</dt>
                <dd className="font-semibold text-foreground">
                  {framework.rarity_score ?? "Pending"}
                </dd>
              </div>
            </dl>
            <Link
              className="mt-5 inline-flex min-h-11 w-full items-center justify-center rounded-[6px] bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90"
              href={`/checkout/${framework.id}`}
            >
              License Framework
            </Link>
          </aside>
        </div>
        <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_360px]">
          <PreviewArtifactBlock framework={framework} />
          <section className="rounded-[8px] border border-border-default bg-surface-2 p-5">
            <h2 className="font-heading text-lg font-bold text-foreground">
              Trust signals
            </h2>
            <ul className="mt-4 grid gap-3 text-sm text-foreground-muted">
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
