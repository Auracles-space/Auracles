/**
 * Foundation status surface for Phase 0.
 *
 * Renders the platform readiness page that the SSR `Home` route consumes.
 * Sidebar identifies the phase; primary panel shows per-component
 * readiness cards driven by the backend health snapshot.
 *
 * Maps to: Phase 0 — Foundation (CLAUDE.md Build Sequence).
 */
import type { HealthResponse } from "@/lib/generated/client";
import { StatusBadge } from "@/components/ui/status-badge";

type FoundationStatusProps = {
  health: HealthResponse;
};

const componentLabels: Record<string, string> = {
  api: "FastAPI",
  database: "Postgres",
  redis: "Redis",
};

/**
 * Phase 0 platform readiness surface backed by the generated health client.
 *
 * @param health - Health API response containing component readiness.
 */
export function FoundationStatus({ health }: FoundationStatusProps) {
  const entries = Object.entries(health.components);

  return (
    <main className="min-h-screen bg-background px-5 py-10 text-foreground md:px-10 md:py-16 lg:py-24">
      <section className="mx-auto grid w-full max-w-[1280px] gap-8 md:grid-cols-[280px_1fr]">
        <aside className="rounded-card border border-border-strong bg-surface-1 p-5">
          <div className="font-heading text-lg font-semibold">Auracles</div>
          <div className="mt-1 text-sm leading-6 text-foreground-muted">
            Phase 0 foundation
          </div>
          <div className="mt-6 border-t border-border-strong pt-5 text-xs uppercase tracking-[0.05em] text-foreground-subtle">
            Platform readiness
          </div>
        </aside>

        <div className="rounded-card border border-border-strong bg-surface-2 p-5 md:p-8">
          <div className="flex flex-col gap-4 border-b border-border-strong pb-6 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.05em] text-foreground-subtle">
                System status
              </p>
              <h1 className="mt-3 max-w-3xl font-heading text-3xl font-semibold text-foreground md:text-5xl">
                Foundation services are{" "}
                {health.status === "ok" ? "ready" : "not ready"}
              </h1>
            </div>
            <StatusBadge
              status={health.status === "ok" ? "ok" : "unavailable"}
            />
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-3">
            {entries.map(([name, component]) => (
              <article
                className="rounded-card border border-border-strong bg-surface-3 p-4"
                key={name}
              >
                <div className="flex min-h-11 items-start justify-between gap-3">
                  <div>
                    <h2 className="font-heading text-base font-semibold text-foreground">
                      {componentLabels[name] ?? name}
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-foreground-muted">
                      {component.detail ?? "Reachable and accepting checks."}
                    </p>
                  </div>
                  <StatusBadge status={component.status} />
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
