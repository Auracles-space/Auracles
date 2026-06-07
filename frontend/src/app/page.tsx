import { FoundationStatus } from "@/components/modules/foundation-status";
import { getHealth, type HealthResponse } from "@/lib/generated/client";

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
