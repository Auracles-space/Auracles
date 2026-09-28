"use client";

/**
 * Client-side demand map for the Contributor workspace.
 *
 * The public `/demand` page is server-rendered, but the workspace is a client
 * shell, so the same data is fetched here and handed to the same presentation
 * component. A Contributor deciding what to build next has no other route to
 * the demand map from inside the product.
 *
 * Maps to: FR-SRCH (search), FR-FWK (framework management).
 */
import { useEffect, useState } from "react";

import { DemandMap } from "@/components/modules/explore/demand-map";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { configureBrowserClient } from "@/lib/auth/form-client";
import { readDemandMapV1ExploreDemandGet } from "@/lib/generated/sdk.gen";
import type { DemandMapResponse } from "@/lib/generated/types.gen";

/**
 * Load and render unmet marketplace demand inside the workspace.
 */
export function DemandPanel() {
  const [demand, setDemand] = useState<DemandMapResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function load(): Promise<void> {
      configureBrowserClient();
      try {
        const result = await readDemandMapV1ExploreDemandGet();
        if (!mounted) {
          return;
        }
        setDemand(result.response.ok && result.data ? result.data : null);
      } catch {
        if (mounted) {
          // DemandMap renders null as "could not be loaded", which is not the
          // same thing as "nobody wants anything".
          setDemand(null);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, []);

  if (loading) {
    return <TableSkeleton />;
  }

  // The workspace tab already titles and explains this panel.
  return <DemandMap demand={demand} showHeader={false} />;
}
