/**
 * Marketplace generated-client helpers.
 *
 * Server Components configure the generated Hey API client here before calling
 * public Explore endpoints. Client Components use the same generated SDK plus
 * auth headers from `form-client`.
 *
 * Invariant: server reads here are public-only. No credentials and no per-user
 * Authorization are ever set on the shared client from the server, so the
 * mutable global config carries no request-scoped secrets. Per-user tokens are
 * passed per call as headers by browser code, never stored on the singleton.
 */
import { resolveApiBaseUrl } from "@/lib/api-base";
import { client } from "@/lib/generated/sdk.gen";

const API_BASE_URL = resolveApiBaseUrl();

/**
 * Configure generated API calls for server-rendered marketplace reads.
 */
export function configureServerMarketplaceClient(): void {
  client.setConfig({
    baseUrl: API_BASE_URL,
    cache: "no-store",
  });
}
