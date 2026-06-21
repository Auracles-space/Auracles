/**
 * Authenticated account settings route.
 *
 * Hosts authenticated identity, GDPR export, and delete-account controls backed
 * by settings and GDPR endpoints.
 */
import { AccountSettingsPanel } from "@/components/modules/settings/account-settings-panel";

/**
 * Render authenticated account settings.
 */
export default function AccountSettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Account settings
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
          Identity and access
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
          Manage verified account details, GDPR export access, and the
          cooling-off delete-account workflow.
        </p>
      </header>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-6">
        <AccountSettingsPanel />
      </section>
    </div>
  );
}
