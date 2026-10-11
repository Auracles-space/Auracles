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
 * Headers identifying this fetch as our own server renderer.
 *
 * Every SSR render reaches the API from this host, so the API sees one address
 * for every visitor's page load and per-IP limiting cannot tell them apart. One
 * noisy source therefore consumes the bucket every render depends on — GPTBot
 * crawling `/explore`'s filter facets drained it on 2026-10-11 and real
 * visitors were shown "Catalog is temporarily unavailable".
 *
 * The secret buys a separate rate-limit bucket and nothing else. It is read
 * from a server-only variable, so it is never bundled into browser code; when
 * it is unset the renderer simply shares the public bucket as before.
 *
 * @returns The internal-caller header, or nothing when unconfigured.
 */
function internalCallerHeaders(): Record<string, string> {
  const secret = process.env.INTERNAL_API_SECRET;
  return secret ? { "X-Internal-Caller": secret } : {};
}

/**
 * Configure generated API calls for server-rendered marketplace reads.
 */
export function configureServerMarketplaceClient(): void {
  client.setConfig({
    baseUrl: API_BASE_URL,
    cache: "no-store",
    headers: internalCallerHeaders(),
  });
}
