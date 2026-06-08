/**
 * Authenticated account settings route.
 *
 * Hosts email-change and deactivation controls backed by settings endpoints.
 */
import { AccountSettingsPanel } from "@/components/modules/settings/account-settings-panel";

export default function AccountSettingsPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Account settings
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Identity and access
          </h1>
          <p className="mt-3 text-sm leading-6 text-foreground-muted">
            Change verified account details after backend confirmation checks.
          </p>
        </header>
        <section className="rounded-[8px] border border-border-default bg-surface-1 p-5">
          <AccountSettingsPanel />
        </section>
      </div>
    </main>
  );
}
