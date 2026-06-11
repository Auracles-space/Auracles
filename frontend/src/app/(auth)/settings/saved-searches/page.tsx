/**
 * Authenticated saved-search settings route.
 *
 * Hosts Operator controls for saved Explore searches and alert preferences.
 */
import { SavedSearchesPanel } from "@/components/modules/settings/saved-searches-panel";

/**
 * Render Operator saved-search settings.
 */
export default function SavedSearchesSettingsPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-4xl">
        <header className="mb-6 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Search settings
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
            Saved searches
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Manage reusable Explore filters and marketplace alert delivery.
          </p>
        </header>
        <SavedSearchesPanel />
      </div>
    </main>
  );
}
