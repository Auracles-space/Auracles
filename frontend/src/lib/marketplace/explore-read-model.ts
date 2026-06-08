/**
 * Explore server read-model helpers.
 *
 * Generated client calls can throw on network failures before returning a
 * normalized API error. These helpers keep SSR pages from crashing when the API
 * is temporarily unavailable.
 */
import { listExploreFrameworks } from "@/lib/generated/sdk.gen";
import type {
  ExploreFrameworkListResponse,
  ListExploreFrameworksData,
} from "@/lib/generated/types.gen";

import { configureServerMarketplaceClient } from "./api";

type ExploreCatalogReadModel = {
  catalog: ExploreFrameworkListResponse | null;
  unavailable: boolean;
};

/**
 * Load the public Explore catalog for an SSR page.
 *
 * @param query - Generated-client Explore query parameters.
 * @returns Catalog data or an unavailable marker when network fetch fails.
 */
export async function loadExploreCatalog(
  query: ListExploreFrameworksData["query"],
): Promise<ExploreCatalogReadModel> {
  configureServerMarketplaceClient();

  try {
    const result = await listExploreFrameworks({ query });

    if (!result.response.ok || !result.data) {
      return { catalog: null, unavailable: true };
    }

    return { catalog: result.data, unavailable: false };
  } catch {
    return { catalog: null, unavailable: true };
  }
}
