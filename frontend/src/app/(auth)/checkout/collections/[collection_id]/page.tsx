/**
 * Authenticated Operator Collection checkout route.
 *
 * Fetches public Collection detail server-side, then hands bundle data into the
 * client checkout form for Stripe Elements confirmation.
 */
import Link from "next/link";
import { notFound } from "next/navigation";

import { CollectionCheckoutForm } from "@/components/modules/financials/checkout-form";
import { getExploreCollectionDetail } from "@/lib/generated/sdk.gen";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";
import { formatMoney } from "@/lib/marketplace/format";

type CollectionCheckoutPageProps = {
  params: Promise<{ collection_id: string }>;
};

/**
 * Render Operator checkout for one published Collection.
 *
 * @param props - Next.js route params.
 */
export default async function CollectionCheckoutPage({
  params,
}: CollectionCheckoutPageProps) {
  const { collection_id: collectionId } = await params;

  configureServerMarketplaceClient();
  const result = await getExploreCollectionDetail({
    path: { collection_id: collectionId },
  });

  if (!result.response.ok || !result.data) {
    notFound();
  }

  const collection = result.data;

  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto grid max-w-[1280px] gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <Link
            className="text-sm font-semibold text-accent"
            href={`/explore/collections/${collection.id}`}
          >
            Back to Collection
          </Link>
          <p className="mt-6 text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Collection checkout
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
            {collection.title}
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-foreground-muted">
            {collection.description}
          </p>

          <dl className="mt-6 grid gap-3 text-sm sm:grid-cols-2">
            <div className="rounded-md border border-border-default bg-surface-2 p-4">
              <dt className="text-foreground-muted">Bundle price</dt>
              <dd className="mt-1 font-semibold text-foreground">
                {formatMoney(collection.bundle_price, collection.currency)}
              </dd>
            </div>
            <div className="rounded-md border border-border-default bg-surface-2 p-4">
              <dt className="text-foreground-muted">Included Frameworks</dt>
              <dd className="mt-1 font-semibold text-foreground">
                {collection.member_count}
              </dd>
            </div>
            <div className="rounded-md border border-success/30 bg-success/10 p-4">
              <dt className="text-success">Savings</dt>
              <dd className="mt-1 font-semibold text-success">
                {formatMoney(collection.savings_amount, collection.currency)}
              </dd>
            </div>
            <div className="rounded-md border border-border-default bg-surface-2 p-4">
              <dt className="text-foreground-muted">Already owned</dt>
              <dd className="mt-1 font-semibold text-foreground">
                {collection.already_owned_member_ids.length}
              </dd>
            </div>
          </dl>
        </section>
        <CollectionCheckoutForm collection={collection} />
      </div>
    </main>
  );
}
