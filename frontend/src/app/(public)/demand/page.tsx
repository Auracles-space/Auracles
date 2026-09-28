/**
 * Public demand map route.
 *
 * Server-rendered: the page is public so that a visitor who is not yet a
 * member can see unmet demand and have a concrete reason to join, and so that
 * terms with real search volume are indexable.
 */
import { DemandMap } from "@/components/modules/explore/demand-map";
import { loadDemandMap } from "@/lib/marketplace/explore-read-model";

export const metadata = {
  title: "Market demand - Auracles",
  description:
    "What Operators searched for on Auracles and did not find. Unmet demand by term and by segment.",
};

/**
 * Render the public demand map.
 */
export default async function DemandPage() {
  const { demand } = await loadDemandMap();

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <DemandMap demand={demand} />
      </div>
    </main>
  );
}
