/**
 * Authenticated Operator checkout route.
 *
 * Fetches public Framework detail server-side, then hands the selected
 * Framework into the client checkout form for Stripe Elements confirmation.
 */
import Link from "next/link";
import { notFound } from "next/navigation";

import { CheckoutForm } from "@/components/modules/financials/checkout-form";
import { getExploreFrameworkDetail } from "@/lib/generated/sdk.gen";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type CheckoutPageProps = {
  params: Promise<{ framework_id: string }>;
};

/**
 * Render Operator checkout for one published Framework.
 *
 * @param props - Next.js route params.
 */
export default async function CheckoutPage({ params }: CheckoutPageProps) {
  const { framework_id: frameworkId } = await params;

  configureServerMarketplaceClient();
  const result = await getExploreFrameworkDetail({
    path: { framework_id: frameworkId },
  });

  if (!result.response.ok || !result.data) {
    notFound();
  }

  const framework = result.data;

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto grid max-w-[1280px] gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <Link
            className="text-sm font-semibold text-accent"
            href={`/explore/${framework.id}`}
          >
            Back to Framework
          </Link>
          <p className="mt-6 text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            {formatLabel(framework.category)}
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
            {framework.title}
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-foreground-muted">
            {framework.description}
          </p>

          <dl className="mt-6 grid gap-3 text-sm sm:grid-cols-2">
            <div className="rounded-xl border border-border-default bg-surface-2 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
              <dt className="text-foreground-muted">Price</dt>
              <dd className="mt-1 font-semibold text-foreground">
                {formatMoney(framework.price, framework.currency)}
              </dd>
            </div>
            <div className="rounded-xl border border-border-default bg-surface-2 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
              <dt className="text-foreground-muted">Version</dt>
              <dd className="mt-1 font-semibold text-foreground">
                {framework.version}
              </dd>
            </div>
            <div className="rounded-xl border border-border-default bg-surface-2 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
              <dt className="text-foreground-muted">Organization</dt>
              <dd className="mt-1 font-semibold text-foreground">
                {formatLabel(framework.org_size)}
              </dd>
            </div>
            <div className="rounded-xl border border-border-default bg-surface-2 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
              <dt className="text-foreground-muted">Rarity</dt>
              <dd className="mt-1 font-semibold text-foreground">
                {framework.rarity_score ?? "Pending"}
              </dd>
            </div>
          </dl>
        </section>
        <CheckoutForm framework={framework} />
      </div>
    </main>
  );
}
