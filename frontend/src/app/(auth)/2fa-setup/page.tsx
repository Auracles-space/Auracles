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
        <header className="mb-6">
          <h1 className="font-heading text-3xl font-bold tracking-tight text-foreground">
            Two-factor authentication (2FA)
          </h1>
          <p className="mt-3 text-sm leading-6 text-foreground-muted">
            Two-factor authentication adds an extra layer of security before executing sensitive account or financial operations.
          </p>
        </header>
        <section className="rounded-card border border-border-default bg-surface-1 p-5 shadow-bento md:p-8">
          <TotpSetupPanel />
        </section>
      </div>
    </main>
  );
}
