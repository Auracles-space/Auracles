/**
 * Marketplace generated-client helpers.
 *
 * Server Components configure the generated Hey API client here before calling
 * public Explore endpoints. Client Components use the same generated SDK plus
 * auth headers from `form-client`.
 */
import { client } from "@/lib/generated/sdk.gen";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Configure generated API calls for server-rendered marketplace reads.
 */
export function configureServerMarketplaceClient(): void {
  client.setConfig({
    baseUrl: API_BASE_URL,
    cache: "no-store",
  });
}
