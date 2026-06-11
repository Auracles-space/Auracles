/**
 * Explore server read-model helpers.
 *
 * Generated client calls can throw on network failures before returning a
 * normalized API error. These helpers keep SSR pages from crashing when the API
 * is temporarily unavailable.
 */
import { listExploreMixedCatalog } from "@/lib/generated/sdk.gen";
import type {
  ExploreCatalogResponse,
  ListMixedCatalogV1ExploreCatalogGetData,
} from "@/lib/generated/types.gen";

import { configureServerMarketplaceClient } from "./api";

type ExploreCatalogReadModel = {
  catalog: ExploreCatalogResponse | null;
  unavailable: boolean;
};

/**
 * Load the public Explore catalog for an SSR page.
 *
 * @param query - Generated-client Explore query parameters.
 * @returns Catalog data or an unavailable marker when network fetch fails.
 */
export async function loadExploreCatalog(
  query: ListMixedCatalogV1ExploreCatalogGetData["query"],
): Promise<ExploreCatalogReadModel> {
  configureServerMarketplaceClient();

  try {
    const result = await listExploreMixedCatalog({ query });

    if (!result.response.ok || !result.data) {
      return { catalog: null, unavailable: true };
    }

    return { catalog: result.data, unavailable: false };
  } catch {
    return { catalog: null, unavailable: true };
  }
}
