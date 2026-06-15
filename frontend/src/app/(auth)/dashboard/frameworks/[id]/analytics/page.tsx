/**
 * Contributor Framework analytics route.
 *
 * Exposes current review aggregates while views, purchases, and per-Framework
 * revenue remain placeholder metrics until dedicated analytics endpoints ship.
 */
import { listFrameworkReviews } from "@/lib/generated/sdk.gen";
import type { FrameworkReviewListResponse } from "@/lib/generated/types.gen";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";

type AnalyticsPageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render Phase 2 analytics placeholders for one Framework.
 *
 * @param props - Next.js route params.
 */
export default async function FrameworkAnalyticsPage({
  params,
}: AnalyticsPageProps) {
  const { id } = await params;
  configureServerMarketplaceClient();
  let reviews: FrameworkReviewListResponse | null = null;
  try {
    const result = await listFrameworkReviews({
      path: { framework_id: id },
    });
    reviews = result.data ?? null;
  } catch {
    reviews = null;
  }
  const averageReview = reviews?.average_score
    ? `${reviews.average_score} (${reviews.review_count})`
    : "No reviews";
  const metrics = [
    { label: "Catalog views", value: "0" },
    { label: "Purchases", value: "0" },
    { label: "Revenue", value: "$0" },
    { label: "Average review", value: averageReview },
  ];

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Framework analytics
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          {id}
        </h1>
        <div className="mt-8 grid gap-4 md:grid-cols-4">
          {metrics.map((metric) => (
            <section
              className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm"
              key={metric.label}
            >
              <p className="text-sm text-foreground-muted">{metric.label}</p>
              <p className="mt-2 font-heading text-3xl font-bold text-foreground">
                {metric.value}
              </p>
            </section>
          ))}
        </div>
      </div>
    </main>
  );
}
