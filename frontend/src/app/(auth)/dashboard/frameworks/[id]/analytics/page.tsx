/**
 * Contributor Framework analytics route.
 *
 * Phase 2 exposes views only. Purchases, revenue, and review average remain
 * zero-value shims until Phase 3 transaction/review flows are implemented.
 */
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
  const metrics = [
    { label: "Catalog views", value: "0" },
    { label: "Purchases", value: "0" },
    { label: "Revenue", value: "$0" },
    { label: "Average review", value: "0" },
  ];

  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
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
              className="rounded-[8px] border border-border-default bg-surface-2 p-5"
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
