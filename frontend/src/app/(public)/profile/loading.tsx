import { Skeleton } from "@/components/ui/skeleton";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";

/**
 * Public Profile page loading state.
 *
 * Suspense fallback that mirrors the structure of the ProfileView page exactly.
 * Prevents visual layout shifts when loading profile details.
 */
export default function ProfileLoading() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px] space-y-8 animate-pulse">
        {/* Back Link Skeleton */}
        <Skeleton className="h-4 w-28 bg-surface-2 rounded-md" />

        {/* Identity Header Skeleton */}
        <section className="rounded-2xl border border-border-default bg-surface-1 p-6 md:p-8">
          <div className="flex flex-col items-start gap-6 md:flex-row">
            {/* Avatar Skeleton */}
            <div className="shrink-0 rounded-2xl border border-border-default p-1 bg-surface-2">
              <Skeleton className="h-24 w-24 md:h-28 md:w-28 rounded-[14px]" />
            </div>

            {/* Profile Text Content Skeletons */}
            <div className="min-w-0 flex-1 space-y-4">
              <div className="flex flex-col gap-4 border-b border-border-default pb-5 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-3 flex-1 min-w-0">
                  {/* Name */}
                  <Skeleton className="h-9 w-64 md:w-80 bg-surface-2 rounded-md" />
                  {/* Headline */}
                  <Skeleton className="h-4 w-full max-w-lg bg-surface-2 rounded-md" />
                  
                  {/* Badges Row */}
                  <div className="flex flex-wrap gap-2 pt-1">
                    <Skeleton className="h-7 w-28 bg-surface-2 rounded-full" />
                    <Skeleton className="h-7 w-20 bg-surface-2 rounded-full" />
                    <Skeleton className="h-7 w-24 bg-surface-2 rounded-full" />
                  </div>
                </div>

                {/* Edit & Website Button Skeletons */}
                <div className="flex shrink-0 items-center gap-2">
                  <Skeleton className="h-9 w-24 bg-surface-2 rounded-xl" />
                  <Skeleton className="h-9 w-28 bg-surface-2 rounded-xl" />
                </div>
              </div>

              {/* Location */}
              <Skeleton className="h-4 w-36 bg-surface-2 rounded-md" />

              {/* Bio lines */}
              <div className="space-y-2 pt-2">
                <Skeleton className="h-4 w-full bg-surface-2 rounded-md" />
                <Skeleton className="h-4 w-5/6 bg-surface-2 rounded-md" />
                <Skeleton className="h-4 w-2/3 bg-surface-2 rounded-md" />
              </div>

              {/* Specializations */}
              <div className="flex flex-wrap gap-2 pt-2">
                <Skeleton className="h-7 w-24 bg-surface-2 rounded-full" />
                <Skeleton className="h-7 w-28 bg-surface-2 rounded-full" />
                <Skeleton className="h-7 w-20 bg-surface-2 rounded-full" />
              </div>
            </div>
          </div>
        </section>

        {/* Links Section Skeleton */}
        <section className="space-y-4">
          <Skeleton className="h-6 w-32 bg-surface-2 rounded-md" />
          <div className="grid gap-3 sm:grid-cols-2">
            <Skeleton className="h-12 w-full bg-surface-1 border border-border-default rounded-xl" />
            <Skeleton className="h-12 w-full bg-surface-1 border border-border-default rounded-xl" />
          </div>
        </section>

        {/* Published Frameworks Section Skeleton */}
        <section className="space-y-4">
          <div className="border-b border-border-default pb-4 space-y-2">
            <Skeleton className="h-6 w-48 bg-surface-2 rounded-md" />
            <Skeleton className="h-4 w-64 bg-surface-2 rounded-md" />
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
