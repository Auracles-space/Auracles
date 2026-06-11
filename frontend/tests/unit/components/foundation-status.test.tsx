/**
 * Foundation status component tests.
 *
 * Verifies that the public status page renders service readiness and degraded
 * infrastructure states from the health API response.
 */
import { render, screen } from "@testing-library/react";

import { FoundationStatus } from "@/components/modules/foundation-status";

describe("FoundationStatus", () => {
  it("renders component readiness from the health API response", () => {
    render(
      <FoundationStatus
        health={{
          status: "ok",
          components: {
            api: { status: "ok" },
            database: { status: "ok" },
            redis: { status: "ok" },
          },
        }}
      />,
    );

    expect(screen.getByText("FastAPI")).toBeInTheDocument();
    expect(screen.getByText("Postgres")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
    expect(screen.getAllByText("Ready")).toHaveLength(4);
  });

  it("renders failure details when a component is unavailable", () => {
    render(
      <FoundationStatus
        health={{
          status: "unhealthy",
          components: {
            api: { status: "ok" },
            database: {
              status: "unavailable",
              detail: "database ping failed",
            },
            redis: { status: "ok" },
          },
        }}
      />,
    );

    expect(screen.getByText("System is Degraded")).toBeInTheDocument();
    expect(screen.getByText("database ping failed")).toBeInTheDocument();
    expect(screen.getAllByText("Down")).toHaveLength(2);
  });
});
