/**
 * Public Framework Detail page loading skeleton.
 *
 * Renders a high-fidelity skeleton page matching the two-column detail page layout
 * to eliminate layout shifts when framework details load.
 *
 * Maps to: FR-EXP-008.
 */
import { Skeleton } from "@/components/ui/skeleton";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";

/**
 * Render framework detail page skeleton.
 */
export default function FrameworkDetailLoading() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        {/* Back Link Placeholder */}
        <div className="text-sm font-semibold text-accent opacity-50 select-none cursor-not-allowed">
          Back to Explore
        </div>

        {/* Two-Column Detail Grid */}
        <div className="mt-6 grid gap-8 lg:grid-cols-[1fr_360px] lg:items-start min-w-0">
          {/* Main Info Column */}
          <section className="min-w-0 rounded-2xl border border-border-default bg-surface-1 p-6 md:p-10 shadow-sm flex flex-col gap-4">
            {/* Category Tag */}
            <Skeleton className="h-4 w-24 rounded-badge bg-surface-2" />

            {/* Title */}
            <div className="space-y-2 mt-2">
              <Skeleton className="h-10 w-3/4 md:h-12 rounded-xl bg-surface-2" />
            </div>

            {/* Description */}
            <div className="space-y-2 mt-4 max-w-3xl">
              <Skeleton className="h-4 w-full bg-surface-2" />
              <Skeleton className="h-4 w-full bg-surface-2" />
              <Skeleton className="h-4 w-4/5 bg-surface-2" />
            </div>

            {/* Contributor Link */}
            <Skeleton className="h-4 w-32 mt-4 rounded bg-surface-2" />

            {/* Tags / Badges Row */}
            <div className="mt-6 flex flex-wrap gap-2">
              <Skeleton className="h-8 w-32 rounded-badge bg-surface-2" />
              <Skeleton className="h-8 w-28 rounded-badge bg-surface-2" />
              <Skeleton className="h-8 w-16 rounded bg-surface-2" />
              <Skeleton className="h-8 w-20 rounded bg-surface-2" />
            </div>
          </section>

          {/* Sidebar Metadata & Checkout Aside */}
          <aside className="min-w-0 sticky top-8 rounded-2xl border border-border-default bg-surface-2 p-6 shadow-sm flex flex-col gap-6">
            <div>
              <p className="text-sm text-foreground-muted">Starting price</p>
              <Skeleton className="mt-2 h-10 w-36 rounded-xl bg-surface-3" />
            </div>
            
            {/* Metadata Grid */}
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Version" },
                { label: "Complexity" },
                { label: "Rarity" },
                { label: "Organization" },
              ].map((item, idx) => (
                <div key={idx} className="rounded-xl border border-border-default bg-surface-1 p-3">
                  <p className="text-[11px] uppercase tracking-wider text-foreground-muted">{item.label}</p>
                  <Skeleton className="mt-2 h-4 w-12 rounded bg-surface-2" />
                </div>
              ))}
              {/* Reviews block (full-width) */}
              <div className="col-span-2 flex items-center justify-between rounded-xl border border-border-default bg-surface-1 p-3">
                <span className="text-[11px] uppercase tracking-wider text-foreground-muted">Reviews</span>
                <Skeleton className="h-4 w-20 rounded bg-surface-2" />
              </div>
            </div>

            {/* Checkout Button CTA Placeholder */}
            <Skeleton className="h-12 w-full rounded-xl bg-surface-3" />
          </aside>
        </div>

        {/* Bottom Row - Artifact Details & Trust Signals */}
        <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_360px] lg:items-start min-w-0">
          {/* Artifact Preview Card */}
          <div className="min-w-0 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm flex flex-col gap-6">
            <Skeleton className="h-6 w-48 rounded bg-surface-2" />
            <div className="border border-border-default rounded-xl p-4 space-y-4">
              <Skeleton className="h-8 w-full rounded bg-surface-2" />
              <Skeleton className="h-20 w-full rounded bg-surface-2" />
              <Skeleton className="h-12 w-full rounded bg-surface-2" />
            </div>
          </div>

          {/* Trust Signals Card */}
          <section className="min-w-0 rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm flex flex-col gap-4">
            <h2 className="font-heading text-lg font-bold text-foreground">
              Trust signals
            </h2>
            <div className="space-y-2.5 mt-2">
              <Skeleton className="h-4 w-full bg-surface-3" />
              <Skeleton className="h-4 w-5/6 bg-surface-3" />
              <Skeleton className="h-4 w-3/4 bg-surface-3" />
            </div>
          </section>
        </div>

        {/* Related Frameworks Row */}
        <div className="mt-10">
          <Skeleton className="h-6 w-48 rounded bg-surface-2 mb-6" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </div>
        </div>
      </div>
    </main>
  );
}
