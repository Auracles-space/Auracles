/**
 * Public Collection detail route.
 *
 * Server-rendered so bundle pricing, savings, member Frameworks, and public
 * contributor metadata are visible before checkout.
 */
import Link from "next/link";
import { BackButton } from "@/components/ui/back-button";
import { notFound } from "next/navigation";

import { getExploreCollectionDetail } from "@/lib/generated/sdk.gen";
import type { ExploreCollectionDetail } from "@/lib/generated/types.gen";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type CollectionDetailPageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render a public Collection bundle detail page.
 *
 * @param props - Next.js route params.
 */
export default async function CollectionDetailPage({
  params,
}: CollectionDetailPageProps) {
  const { id } = await params;

  configureServerMarketplaceClient();
  const result = await getExploreCollectionDetail({
    path: { collection_id: id },
  });

  if (!result.response.ok || !result.data) {
    notFound();
  }

  const collection: ExploreCollectionDetail = result.data;
  const alreadyOwnedCount = collection.already_owned_member_ids?.length ?? 0;

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <BackButton fallbackHref="/explore">
          Back to Explore
        </BackButton>
        <div className="mt-6 grid gap-8 lg:grid-cols-[1fr_360px] lg:items-start">
          <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-10">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Collection
            </p>
            <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-5xl">
              {collection.title}
            </h1>
            <p className="mt-4 max-w-3xl text-base leading-7 text-foreground-muted">
              {collection.description}
            </p>
            <Link
              className="mt-4 inline-flex min-h-12 items-center text-sm font-semibold text-accent transition hover:text-accent/80"
              href={`/profile/${collection.contributor_id}`}
            >
              {collection.contributor_name}
            </Link>
          </section>

          <aside className="sticky top-8 rounded-2xl border border-border-default bg-surface-2 p-6 shadow-sm">
            <p className="text-sm text-foreground-muted">Bundle price</p>
            <p className="mt-1 font-heading text-4xl font-bold text-foreground">
              {formatMoney(collection.bundle_price, collection.currency)}
            </p>
            <div className="mt-6 grid gap-3 text-sm">
              <div className="rounded-xl border border-border-default bg-surface-1 p-3">
                <p className="text-[11px] font-bold uppercase tracking-wider text-foreground-muted">Member value</p>
                <p className="mt-1 font-semibold text-foreground">
                  {formatMoney(collection.member_price_sum, collection.currency)}
                </p>
              </div>
              <div className="rounded-xl border border-success/30 bg-success/10 p-3 text-success">
                Save <span className="font-bold">{formatMoney(collection.savings_amount, collection.currency)}</span> ({collection.savings_percent}%)
              </div>
              {alreadyOwnedCount > 0 && (
                <div className="rounded-xl border border-info/30 bg-info/10 p-3 text-info">
                  You already own <span className="font-bold">{alreadyOwnedCount}</span> member{alreadyOwnedCount === 1 ? "" : "s"}
                </div>
              )}
            </div>
            <Link
              className="mt-6 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-accent px-4 py-2 text-sm font-bold tracking-wide text-white shadow-[0_4px_14px_0_rgba(199,70,52,0.39)] outline-none transition-all hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
              href={`/checkout/collections/${collection.id}`}
            >
              License Collection
            </Link>
          </aside>
        </div>

        <section className="mt-8 rounded-2xl border border-border-default bg-surface-2 p-6 shadow-sm">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Included Frameworks
          </h2>
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            {collection.members.map((member) => (
              <article
                className="group flex flex-col justify-between rounded-xl border border-border-default bg-surface-1 p-5 transition-colors hover:bg-surface-2"
                key={member.framework_id}
              >
                <div>
                  <h3 className="font-heading text-lg font-bold text-foreground transition-colors group-hover:text-accent">
                    {member.title}
                  </h3>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className="inline-flex rounded-md border border-border-default bg-background px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-foreground-muted">
                      {formatLabel(member.category)}
                    </span>
                    <span className="inline-flex rounded-md border border-border-default bg-background px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-foreground-muted">
                      v{member.version}
                    </span>
                  </div>
                </div>
                <div className="mt-4 border-t border-border-default pt-4 text-right">
                  <p className="font-heading text-sm font-bold text-foreground">
                    {formatMoney(member.price, member.currency)}
                  </p>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-foreground-muted">
                    Standalone value
                  </p>
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
