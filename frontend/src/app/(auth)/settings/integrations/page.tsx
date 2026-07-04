/**
 * Connected Accounts settings page.
 *
 * Hosts the integrations list where contributors connect external file
 * providers (Google Drive) used by the artifact import picker.
 */
import { Suspense } from "react";

import { IntegrationsList } from "@/components/modules/settings/integrations-list";

export default function IntegrationsSettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Connected Accounts
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Manage integrations
        </h1>
        <p className="mt-3 text-sm leading-6 text-foreground-muted">
          Connect third-party accounts to import artifacts and data directly
          into your frameworks.
        </p>
      </header>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
        <Suspense
          fallback={
            <p className="p-4 text-sm text-foreground-muted">
              Loading connections…
            </p>
          }
        >
          <IntegrationsList />
        </Suspense>
      </section>
    </div>
  );
}
