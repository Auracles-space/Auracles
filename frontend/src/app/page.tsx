/**
 * Foundation status page (SSR).
 *
 * Renders the Phase 0 readiness check by calling the backend `/v1/health`
 * endpoint via the generated client. Used during early development to
 * confirm that the FastAPI + Postgres + Redis stack is reachable.
 *
 * Maps to: Phase 0 — Foundation (CLAUDE.md Build Sequence).
 */
import { FoundationStatus } from "@/components/modules/foundation-status";
import { getHealth, type HealthResponse } from "@/lib/generated/client";

/**
 * Fetch the health snapshot from the backend, falling back to an
 * "unavailable" payload if the API cannot be reached.
 *
 * @returns Health response describing API, database, and Redis state.
 */
async function loadHealth(): Promise<HealthResponse> {
  try {
    const result = await getHealth();
    return result.data;
  } catch {
    return {
      status: "unhealthy",
      components: {
        api: {
          status: "unavailable",
          detail: "FastAPI health endpoint is unreachable.",
        },
        database: {
          status: "unavailable",
          detail: "Postgres status cannot be confirmed.",
        },
        redis: {
          status: "unavailable",
          detail: "Redis status cannot be confirmed.",
        },
      },
    };
  }
}

export default async function Home() {
  const health = await loadHealth();

  return <FoundationStatus health={health} />;
}
