/**
 * Related public Frameworks.
 *
 * Uses the same card primitive as Explore so trust signals remain consistent.
 */
import type { ExploreFrameworkCard } from "@/lib/generated/types.gen";

import { FrameworkCard } from "./framework-card";

type RelatedFrameworksProps = {
  frameworks: ExploreFrameworkCard[];
};

/**
 * Render related Framework recommendations.
 *
 * @param props - Related public Framework cards.
 */
export function RelatedFrameworks({ frameworks }: RelatedFrameworksProps) {
  if (frameworks.length === 0) {
    return null;
  }

  return (
    <section>
      <h2 className="mb-4 font-heading text-xl font-bold text-foreground">
        Related frameworks
      </h2>
      <div className="grid gap-4 lg:grid-cols-3">
        {frameworks.map((framework) => (
          <FrameworkCard framework={framework} key={framework.id} />
        ))}
      </div>
    </section>
  );
}
