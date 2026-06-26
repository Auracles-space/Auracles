/**
 * Public Contributor Profile page loading skeleton.
 *
 * Renders a high-fidelity skeleton page matching the public contributor profile layout
 * to eliminate layout shifts when profile details and published works load.
 *
 * Maps to: FR-EXP-011.
 */
import { Skeleton } from "@/components/ui/skeleton";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";

/**
 * Render contributor profile loading page.
 */
export default function ContributorProfileLoading() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        {/* Back Link Placeholder */}
        <div className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent opacity-50 select-none cursor-not-allowed">
          <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Back to Explore
        </div>

        {/* Profile Card Mockup Section */}
        <section className="mt-6 rounded-2xl border border-border-default bg-surface-1 p-6 md:p-8 shadow-bento">
          <div className="flex flex-col md:flex-row gap-6 items-start w-full">
            {/* Avatar block skeleton */}
            <div className="relative flex h-24 w-24 md:h-28 md:w-28 items-center justify-center overflow-hidden rounded-2xl border border-border-default bg-surface-2 animate-pulse shrink-0" />

            <div className="min-w-0 flex-1 w-full">
              {/* Header and website button placeholder */}
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-border-default pb-5">
                <div className="space-y-3">
                  <div className="flex flex-col md:flex-row md:items-center gap-3">
                    <Skeleton className="h-9 w-48 rounded-xl bg-surface-2" />
                    <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                      <Skeleton className="h-6 w-16 rounded bg-surface-2" />
                      <Skeleton className="h-6 w-24 rounded bg-surface-2" />
                    </div>
                  </div>
                  <Skeleton className="h-4 w-64 rounded bg-surface-2" />
                </div>
              </div>

              {/* Bio description */}
              <div className="space-y-2 mt-4 max-w-4xl">
                <Skeleton className="h-4 w-full bg-surface-2" />
                <Skeleton className="h-4 w-2/3 bg-surface-2" />
              </div>

              {/* Bento Stats Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
                {[1, 2, 3].map((idx) => (
                  <div key={idx} className="rounded-xl border border-border-default/60 bg-surface-2 p-4 flex items-center gap-4">
                    <Skeleton className="h-10 w-10 bg-surface-3 rounded-xl" />
                    <div className="space-y-1.5">
                      <Skeleton className="h-3 w-16 bg-surface-3" />
                      <Skeleton className="h-4 w-24 bg-surface-3" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Frameworks listing placeholder */}
        <section className="mt-10">
          <div className="mb-4 border-b border-border-default pb-4">
            <Skeleton className="h-6 w-48 rounded bg-surface-2" />
            <Skeleton className="h-4 w-80 rounded bg-surface-2 mt-2" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </div>
        </section>
      </div>
    </main>
  );
}
