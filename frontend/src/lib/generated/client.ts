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

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
