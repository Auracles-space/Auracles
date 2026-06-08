import { describe, expect, it, vi } from "vitest";

import { loadExploreCatalog } from "@/lib/marketplace/explore-read-model";
import { listExploreFrameworks } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
  },
  listExploreFrameworks: vi.fn(),
}));

describe("Explore read model", () => {
  it("returns an unavailable state instead of throwing when SSR fetch fails", async () => {
    vi.mocked(listExploreFrameworks).mockRejectedValue(new TypeError("fetch failed"));

    const result = await loadExploreCatalog({ page: 1, page_size: 12 });

    expect(result).toEqual({
      catalog: null,
      unavailable: true,
    });
  });
});
