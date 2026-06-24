/**
 * Hand-written wrapper around the generated Hey API SDK.
 *
 * Centralises base URL resolution (`NEXT_PUBLIC_API_URL`), no-store
 * caching, and result normalisation so route components consume a
 * stable, typed interface instead of touching the generated SDK
 * directly. Re-exports the generated types.
 *
 * Maps to: pre-scale infra design Section 4 (frontend env vars) and
 * CLAUDE.md Frontend Code Standards (generated client only).
 */
import { resolveApiBaseUrl } from "@/lib/api-base";
import {
  client,
  getHealth as generatedGetHealth,
} from "@/lib/generated/sdk.gen";
import type { HealthResponse } from "@/lib/generated/types.gen";

export type { ComponentHealth, HealthResponse } from "@/lib/generated/types.gen";

export type HealthResult = {
  ok: boolean;
  status: number;
  data: HealthResponse;
};

const API_BASE_URL = resolveApiBaseUrl();

/**
 * Fetch platform readiness from the backend `/v1/health` endpoint.
 *
 * @returns Parsed health response with HTTP status flags.
 * @throws Error when the API returns no payload (data or error).
 */
export async function getHealth(): Promise<HealthResult> {
  client.setConfig({
    baseUrl: API_BASE_URL,
    cache: "no-store",
  });
  const result = await generatedGetHealth();
  const data = result.data ?? result.error;

  if (!data) {
    throw new Error("Health API returned no response body.");
  }

  return {
    ok: result.response.ok,
    status: result.response.status,
    data,
  };
}
