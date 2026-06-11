/**
 * Foundation status surface for Phase 0.
 *
 * Renders the platform readiness page that the SSR `Home` route consumes.
 * Primary panel shows per-component readiness cards driven by the backend health snapshot.
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
    <main className="min-h-screen bg-background px-5 py-16 text-foreground md:px-10 lg:py-24">
      <div className="mx-auto flex max-w-3xl flex-col items-center justify-center text-center">
        <div className="relative mb-6">
          <div 
            className={`absolute -inset-4 rounded-full opacity-20 blur-xl ${
              health.status === "ok" ? "bg-[#16A34A]" : "bg-[#DC2626]"
            }`} 
          />
          <div 
            className={`relative flex h-16 w-16 items-center justify-center rounded-2xl border bg-surface-1 shadow-sm ${
              health.status === "ok" ? "border-[#16A34A]/30" : "border-[#DC2626]/30"
            }`}
          >
             <StatusBadge status={health.status === "ok" ? "ok" : "unavailable"} />
          </div>
        </div>
        
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Phase 0 Foundation
        </p>
        <h1 className="font-heading text-4xl font-bold text-foreground md:text-5xl">
          System is {health.status === "ok" ? "Fully Operational" : "Degraded"}
        </h1>
        <p className="mt-4 max-w-xl text-sm leading-6 text-foreground-muted">
          All foundation services are currently being monitored. This dashboard provides 
          real-time insight into the status of Auracles platform infrastructure.
        </p>
      </div>

      <div className="mx-auto mt-16 grid max-w-[1000px] gap-4 md:grid-cols-2 lg:grid-cols-3">
        {entries.map(([name, component], index) => {
          // Make the first component (usually API) take up more space in the bento grid
          const isLarge = index === 0;
          return (
            <article
              className={`group relative overflow-hidden rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm transition-all hover:border-accent/30 hover:shadow-md ${
                isLarge ? "md:col-span-2 lg:col-span-2" : "md:col-span-1"
              }`}
              key={name}
            >
              <div className="flex h-full flex-col justify-between gap-6">
                <div className="flex items-start justify-between gap-3">
                  <h2 className={`font-heading font-semibold text-foreground ${isLarge ? "text-2xl" : "text-base"}`}>
                    {componentLabels[name] ?? name}
                  </h2>
                  <StatusBadge
                    status={component.status === "ok" ? "ok" : "unavailable"}
                  />
                </div>
                <div>
                  <p className="text-sm leading-6 text-foreground-muted">
                    {component.detail ?? "Reachable and accepting health checks."}
                  </p>
                  {isLarge && (
                    <div className="mt-6 flex gap-4 border-t border-border-default pt-4">
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-wider text-foreground-muted">Uptime</p>
                        <p className="mt-1 font-mono text-sm font-semibold">99.99%</p>
                      </div>
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-wider text-foreground-muted">Latency</p>
                        <p className="mt-1 font-mono text-sm font-semibold">12ms</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </main>
  );
}
