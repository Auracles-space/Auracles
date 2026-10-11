import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadExploreCatalog } from "@/lib/marketplace/explore-read-model";
import { client, listExploreMixedCatalog } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
    getConfig: vi.fn(() => ({})),
  },
  listExploreMixedCatalog: vi.fn(),
}));

/** The options the read model passed to the SDK on its first call. */
function firstCallOptions(): { headers?: Record<string, string> } {
  return vi.mocked(listExploreMixedCatalog).mock.calls[0][0] as {
    headers?: Record<string, string>;
  };
}

describe("Explore read model", () => {
  it("returns an unavailable state instead of throwing when SSR fetch fails", async () => {
    vi.mocked(listExploreMixedCatalog).mockRejectedValue(
      new TypeError("fetch failed"),
    );

    const result = await loadExploreCatalog({ page: 1, page_size: 12 });

    expect(listExploreMixedCatalog).toHaveBeenCalledWith(
      // objectContaining because the call also carries the internal-caller
      // header; the query is what this test is about.
      expect.objectContaining({ query: { page: 1, page_size: 12 } }),
    );
    expect(result).toEqual({
      catalog: null,
      unavailable: true,
    });
  });
});

describe("Explore read model internal-caller header", () => {
  // The generated client is a module-level singleton and `setConfig` replaces
  // the whole config, so a header left there is blanked by any other caller —
  // `getHealth` did exactly that, for every SSR render in flight, because Next
  // serves concurrent renders from one process. That left 17% of catalog reads
  // still rate-limited after the bucket itself was fixed, and visitors still
  // saw "Catalog is temporarily unavailable".
  beforeEach(() => {
    vi.mocked(listExploreMixedCatalog).mockReset();
    vi.mocked(listExploreMixedCatalog).mockResolvedValue({
      response: { ok: true },
      data: { items: [], total: 0 },
    } as never);
    vi.stubEnv("INTERNAL_API_SECRET", "the-internal-secret");
  });

  it("sends the header on the request itself, not via client config", async () => {
    await loadExploreCatalog({ page: 1 });

    expect(firstCallOptions().headers?.["X-Internal-Caller"]).toBe(
      "the-internal-secret",
    );
  });

  it("still sends it after another caller replaces the client config", async () => {
    client.setConfig({ baseUrl: "https://api.test" } as never);

    await loadExploreCatalog({ page: 1 });

    expect(firstCallOptions().headers?.["X-Internal-Caller"]).toBe(
      "the-internal-secret",
    );
  });

  it("omits the header when no secret is configured", async () => {
    // Unset must mean "share the public bucket", never "send an empty secret".
    vi.stubEnv("INTERNAL_API_SECRET", "");

    await loadExploreCatalog({ page: 1 });

    expect(firstCallOptions().headers?.["X-Internal-Caller"]).toBeUndefined();
  });
});
