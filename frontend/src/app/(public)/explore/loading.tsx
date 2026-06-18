/**
 * Explore catalog loading state.
 *
 * Suspense fallback rendered while the server fetches the deduped catalog for a
 * new search/filter navigation. Mirrors the results grid so the layout does not
 * shift when real cards arrive.
 */
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";

const PLACEHOLDER_COUNT = 8;

/**
 * Render skeleton cards in the Explore results grid shape.
 */
export default function ExploreLoading() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading frameworks"
      className="grid gap-4 px-4 py-8 sm:grid-cols-2 md:px-8 xl:grid-cols-3 2xl:grid-cols-4"
    >
      {Array.from({ length: PLACEHOLDER_COUNT }).map((_, index) => (
        <CardSkeleton key={index} />
      ))}
    </div>
  );
}
