/**
 * Authenticated consent settings route.
 *
 * Hosts current legal-version acceptance and append-only consent history for
 * the authenticated user. This is the landing page for consent-required
 * redirects raised by privileged backend actions.
 */
import { ConsentSettingsPanel } from "@/components/modules/settings/consent-settings-panel";

/**
 * Render legal consent settings for authenticated users.
 */
export default function ConsentSettingsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-4xl">
        <header className="mb-6 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Legal settings
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
            Consent
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Review the latest legal document versions and record acceptance when
            privileged actions require it.
          </p>
        </header>
        <ConsentSettingsPanel />
      </div>
    </main>
  );
}
