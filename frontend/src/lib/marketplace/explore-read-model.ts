/**
 * Explore server read-model helpers.
 *
 * Generated client calls can throw on network failures before returning a
 * normalized API error. These helpers keep SSR pages from crashing when the API
 * is temporarily unavailable.
 */
import {
  listExploreMixedCatalog,
  readDemandMapV1ExploreDemandGet,
} from "@/lib/generated/sdk.gen";
import type {
  DemandMapResponse,
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

type DemandReadModel = {
  demand: DemandMapResponse | null;
};

/**
 * Load the public demand map for an SSR page.
 *
 * A failed fetch returns null rather than an empty map: "nobody wants
 * anything" is a false signal a Contributor could act on, so the page must be
 * able to tell the two apart.
 *
 * @returns Demand data, or null when the API is unavailable.
 */
export async function loadDemandMap(): Promise<DemandReadModel> {
  configureServerMarketplaceClient();

  try {
    const result = await readDemandMapV1ExploreDemandGet();

    if (!result.response.ok || !result.data) {
      return { demand: null };
    }

    return { demand: result.data };
  } catch {
    return { demand: null };
  }
}
