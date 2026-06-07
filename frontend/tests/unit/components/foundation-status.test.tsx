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

    expect(screen.getByText("Foundation services are not ready")).toBeInTheDocument();
    expect(screen.getByText("database ping failed")).toBeInTheDocument();
    expect(screen.getAllByText("Down")).toHaveLength(2);
  });
});
