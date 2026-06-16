/**
 * Authenticated 2FA setup route.
 *
 * Rendered inside the shared AuthenticatedAppShell.
 */
import { TotpSetupPanel } from "@/components/modules/auth/totp-setup-panel";

export default function TotpSetupPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Account protection
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Two-factor authentication (2FA)
          </h1>
          <p className="mt-3 text-sm leading-6 text-foreground-muted">
            Two-factor authentication adds an extra layer of security before executing sensitive account or financial operations.
          </p>
        </header>
        <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-8">
          <TotpSetupPanel />
        </section>
      </div>
    </main>
  );
}
