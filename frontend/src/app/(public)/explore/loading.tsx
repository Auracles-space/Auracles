/**
 * Explore catalog loading state.
 *
 * Suspense fallback rendered while the server fetches the deduped catalog for a
 * new search/filter navigation. Mirrors the full catalog and sidebar layout
 * so the page does not suffer layout width shifts when real content arrives.
 */
import { Skeleton } from "@/components/ui/skeleton";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";

const PLACEHOLDER_COUNT = 8;

/**
 * Render desktop sidebar filters skeletons.
 */
function SidebarSkeleton() {
  return (
    <div className="space-y-6 select-none">
      {/* Search Input Skeleton */}
      <div className="space-y-1.5">
        <Skeleton className="h-4 w-16 bg-surface-2" />
        <Skeleton className="h-10 w-full rounded-xl bg-surface-2" />
      </div>

      {/* Filter Groups Skeletons */}
      {[
        { label: "Sector", lines: 3 },
        { label: "Industry", lines: 4 },
        { label: "Function", lines: 3 },
        { label: "Category", lines: 2 },
        { label: "Attestation", lines: 3 },
      ].map((group) => (
        <div key={group.label} className="space-y-2 border-b border-border-default pb-4">
          <Skeleton className="h-4 w-20 bg-surface-2" />
          <div className="space-y-2 pl-1">
            {Array.from({ length: group.lines }).map((_, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <Skeleton className="h-3.5 w-3.5 rounded bg-surface-2 shrink-0" />
                <Skeleton className="h-3 w-2/3 bg-surface-2" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Render framework cards and sidebar layout skeleton.
 */
export default function ExploreLoading() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto w-full max-w-[1600px]">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
          {/* Left Sidebar Skeleton (Desktop only, mobile renders collapsed accordion) */}
          <div className="w-full lg:sticky lg:top-20 lg:w-64 lg:shrink-0 lg:self-start">
            {/* Mobile Filters Accordion Placeholder */}
            <div className="block lg:hidden mb-4">
              <div className="rounded-xl border border-border-default bg-surface-1 p-4 flex items-center justify-between">
                <Skeleton className="h-4 w-16 bg-surface-2" />
                <Skeleton className="h-4 w-4 rounded-full bg-surface-2" />
              </div>
            </div>

            {/* Desktop Sidebar */}
            <div className="hidden lg:block">
              <SidebarSkeleton />
            </div>
          </div>

          {/* Right Main Section Skeleton */}
          <section className="flex-1 min-w-0">
            {/* Catalog header row */}
            <div className="mb-6 flex items-center justify-between border-b border-border-default pb-4">
              <Skeleton className="h-4 w-32 bg-surface-2" />
              <Skeleton className="h-8 w-24 rounded-lg bg-surface-2" />
            </div>

            {/* Save search action box placeholder */}
            <div className="mb-6">
              <Skeleton className="h-10 w-44 rounded-xl bg-surface-2" />
            </div>

            {/* Frameworks Grid */}
            <div
              aria-busy="true"
              aria-label="Loading frameworks"
              className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
            >
              {Array.from({ length: PLACEHOLDER_COUNT }).map((_, index) => (
                <CardSkeleton key={index} />
              ))}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
